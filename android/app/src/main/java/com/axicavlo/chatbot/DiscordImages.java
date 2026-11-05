package com.axicavlo.chatbot;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageDecoder;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.Animatable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.LruCache;
import android.widget.ImageView;
import java.lang.ref.WeakReference;
import java.net.URL;
import java.net.HttpURLConnection;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONArray;

final class DiscordImages {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService workers = Executors.newFixedThreadPool(3);
    private final LruCache<String, byte[]> cache = new LruCache<String, byte[]>(8 * 1024 * 1024) {
        @Override protected int sizeOf(String key, byte[] value) { return value.length; }
    };
    private final Map<String, List<WeakReference<ImageView>>> pending = new HashMap<>();
    private final Map<String, Long> failed = new LinkedHashMap<>();
    private boolean closed;

    private boolean allowed(String url) {
        try {
            URL parsed = new URL(url);
            return "https".equals(parsed.getProtocol()) && ("cdn.discordapp.com".equals(parsed.getHost())
                || "media.discordapp.net".equals(parsed.getHost()) || "cdn.kamibot.app".equals(parsed.getHost())
                || parsed.getHost().matches("images-ext-\\d+\\.discordapp\\.net"));
        } catch (Exception error) { return false; }
    }

    private boolean display(byte[] data, ImageView view) {
        try {
            if (Build.VERSION.SDK_INT >= 28) {
                Drawable drawable = ImageDecoder.decodeDrawable(ImageDecoder.createSource(ByteBuffer.wrap(data)),
                    (decoder, info, source) -> {
                        int width = info.getSize().getWidth(), height = info.getSize().getHeight();
                        double scale = Math.min(1.0, 640.0 / Math.max(width, height));
                        decoder.setTargetSize(Math.max(1, (int)(width * scale)), Math.max(1, (int)(height * scale)));
                    });
                view.setImageDrawable(drawable);
                if (drawable instanceof Animatable) ((Animatable) drawable).start();
            } else {
                BitmapFactory.Options options = new BitmapFactory.Options(); options.inJustDecodeBounds = true;
                BitmapFactory.decodeByteArray(data, 0, data.length, options);
                int width = options.outWidth, height = options.outHeight; options.inJustDecodeBounds = false; options.inSampleSize = 1;
                while (Math.max(width, height) / options.inSampleSize > 640) options.inSampleSize *= 2;
                Bitmap bitmap = BitmapFactory.decodeByteArray(data, 0, data.length, options);
                if (bitmap == null) return false;
                view.setImageBitmap(bitmap);
            }
            return true;
        } catch (Exception error) { return false; }
    }

    void load(String url, ImageView view) { load(url, view, false, null); }
    void load(String url, ImageView view, boolean media) { load(url, view, media, null); }
    void load(String url, ImageView view, boolean media, JSONArray alternatives) {
        if (closed || !allowed(url)) return;
        if (url.equals(view.getTag()) && view.getDrawable() != null) {
            if (view.getDrawable() instanceof Animatable) ((Animatable) view.getDrawable()).start();
            return;
        }
        view.setTag(url);
        byte[] hit = cache.get(url);
        if (hit != null && display(hit, view)) return;
        if (failed.containsKey(url) && failed.get(url) > SystemClock.uptimeMillis()) return;
        List<WeakReference<ImageView>> waiters = pending.get(url);
        if (waiters != null) {
            for (WeakReference<ImageView> reference : waiters) if (reference.get() == view) return;
            waiters.add(new WeakReference<>(view)); return;
        }
        waiters = new ArrayList<>(); waiters.add(new WeakReference<>(view)); pending.put(url, waiters);
        List<String> candidates = new ArrayList<>(); candidates.add(url);
        if (alternatives != null) for (int i = 0; i < alternatives.length(); i++) {
            String candidate = alternatives.optString(i);
            if (allowed(candidate) && !candidates.contains(candidate)) candidates.add(candidate);
        }
        workers.execute(() -> {
            byte[] result = null;
            for (String candidate : candidates) {
                HttpURLConnection connection = null;
                try {
                    connection = (HttpURLConnection) new URL(candidate).openConnection();
                    connection.setRequestProperty("User-Agent", "DiscordBotChat/" + BuildConfig.VERSION_NAME);
                    connection.setRequestProperty("Accept", "image/*"); connection.setRequestProperty("Referer", "https://discord.com/");
                    connection.setConnectTimeout(8000); connection.setReadTimeout(8000); connection.setInstanceFollowRedirects(false);
                    if (connection.getResponseCode() != 200) throw new java.io.IOException();
                    try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                        byte[] buffer = new byte[4096]; int count;
                        while ((count = input.read(buffer)) != -1) {
                            if (output.size() + count > (media ? 8 : 1) * 1024 * 1024) throw new java.io.IOException();
                            output.write(buffer, 0, count);
                        }
                        byte[] bytes = output.toByteArray();
                        BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
                        BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
                        if (bounds.outWidth <= 0 || bounds.outHeight <= 0
                            || (long) bounds.outWidth * bounds.outHeight > (media ? 20000000 : 512 * 512)) throw new java.io.IOException();
                        result = bytes;
                    }
                    break;
                } catch (Exception ignored) { }
                finally { if (connection != null) connection.disconnect(); }
            }
            final byte[] data = result;
            main.post(() -> {
                List<WeakReference<ImageView>> targets = pending.remove(url);
                if (closed) return;
                if (data != null) cache.put(url, data);
                else {
                    failed.put(url, SystemClock.uptimeMillis() + 30000);
                    if (failed.size() > 512) failed.remove(failed.keySet().iterator().next());
                }
                if (data != null && targets != null) for (WeakReference<ImageView> reference : targets) {
                    ImageView target = reference.get();
                    if (target != null && url.equals(target.getTag())) display(data, target);
                }
            });
        });
    }
    void close() { closed = true; workers.shutdownNow(); pending.clear(); cache.evictAll(); }
}
