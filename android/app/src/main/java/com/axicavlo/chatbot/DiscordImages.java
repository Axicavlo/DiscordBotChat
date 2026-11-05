package com.axicavlo.chatbot;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
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
import java.util.*;
import java.util.concurrent.*;

/** Memory cache and bounded workers; views are touched only on the main thread. */
final class DiscordImages {
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService workers = Executors.newFixedThreadPool(3);
    private final LruCache<String, Bitmap> cache = new LruCache<String, Bitmap>(4 * 1024 * 1024) {
        @Override protected int sizeOf(String key, Bitmap value) { return value.getByteCount(); }
    };
    private final Map<String, List<WeakReference<ImageView>>> pending = new HashMap<>();
    private final Map<String, Long> failed = new LinkedHashMap<>();
    private boolean closed;

    void load(String url, ImageView view) {
        view.setTag(url);
        if (closed || url.isEmpty()) return;
        try {
            URL parsed = new URL(url);
            if (!"https".equals(parsed.getProtocol()) || !("cdn.discordapp.com".equals(parsed.getHost())
                    || "media.discordapp.net".equals(parsed.getHost()))) return;
        } catch (Exception e) { return; }
        Bitmap hit = cache.get(url);
        if (hit != null) { view.setImageBitmap(hit); return; }
        if (failed.containsKey(url) && failed.get(url) > SystemClock.uptimeMillis()) return;
        List<WeakReference<ImageView>> waiters = pending.get(url);
        if (waiters != null) { waiters.add(new WeakReference<>(view)); return; }
        waiters = new ArrayList<>(); waiters.add(new WeakReference<>(view)); pending.put(url, waiters);
        workers.execute(() -> {
            Bitmap bitmap = null;
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setRequestProperty("User-Agent", "DiscordBotChat/" + BuildConfig.VERSION_NAME);
                connection.setConnectTimeout(8000); connection.setReadTimeout(8000);
                connection.setInstanceFollowRedirects(false);
                if (connection.getResponseCode() != 200) throw new java.io.IOException();
                try (InputStream input = connection.getInputStream(); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[4096]; int count;
                    while ((count = input.read(buffer)) != -1) {
                        if (output.size() + count > 1024 * 1024) throw new java.io.IOException();
                        output.write(buffer, 0, count);
                    }
                    byte[] data = output.toByteArray();
                    BitmapFactory.Options bounds = new BitmapFactory.Options(); bounds.inJustDecodeBounds = true;
                    BitmapFactory.decodeByteArray(data, 0, data.length, bounds);
                    if (bounds.outWidth <= 0 || bounds.outHeight <= 0 || bounds.outWidth > 512 || bounds.outHeight > 512)
                        throw new java.io.IOException();
                    bitmap = BitmapFactory.decodeByteArray(data, 0, data.length);
                }
            } catch (Exception ignored) { }
            finally { if (connection != null) connection.disconnect(); }
            final Bitmap result = bitmap;
            main.post(() -> {
                List<WeakReference<ImageView>> targets = pending.remove(url);
                if (closed) return;
                if (result != null) cache.put(url, result);
                else {
                    failed.put(url, SystemClock.uptimeMillis() + 30000);
                    if (failed.size() > 512) failed.remove(failed.keySet().iterator().next());
                }
                if (result != null && targets != null) for (WeakReference<ImageView> reference : targets) {
                    ImageView target = reference.get();
                    if (target != null && url.equals(target.getTag())) target.setImageBitmap(result);
                }
            });
        });
    }

    void close() { closed = true; workers.shutdownNow(); pending.clear(); cache.evictAll(); }
}
