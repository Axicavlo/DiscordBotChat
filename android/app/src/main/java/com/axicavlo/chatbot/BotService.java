package com.axicavlo.chatbot;

import android.app.*;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.util.concurrent.*;
import org.json.JSONObject;

public class BotService extends Service {
    static volatile BotService instance;
    volatile String snapshot = "{}";
    private final ScheduledExecutorService worker = Executors.newSingleThreadScheduledExecutor();
    private PyObject client;
    private String pendingToken;
    private boolean stopping;
    private String lastStatus = "";

    @Override public void onCreate() {
        super.onCreate();
        instance = this;
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(new NotificationChannel("connection", "봇 연결", NotificationManager.IMPORTANCE_LOW));
        }
        startForeground(1, notification("연결 준비 중…"));
        worker.execute(() -> {
            try {
                if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
                client = Python.getInstance().getModule("mobile_client").get("client");
            } catch (Exception e) { fail("앱 초기화에 실패했습니다."); }
        });
        worker.scheduleWithFixedDelay(this::update, 0, 400, TimeUnit.MILLISECONDS);
    }

    private Notification notification(String status) {
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), PendingIntent.FLAG_IMMUTABLE);
        Intent stopIntent = new Intent(this, BotService.class).setAction("disconnect");
        PendingIntent stop = PendingIntent.getService(this, 1, stopIntent, PendingIntent.FLAG_IMMUTABLE);
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, "connection") : new Notification.Builder(this);
        return builder.setContentTitle("채팅봇").setContentText(status)
            .setSmallIcon(android.R.drawable.stat_notify_chat).setContentIntent(open).setOngoing(true)
            .addAction(new Notification.Action.Builder(null, "연결 종료", stop).build()).build();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null) {
            String action = intent.getAction();
            if ("connect".equals(action)) command("connect", intent.getStringExtra("token"), "", "", false);
            else if ("disconnect".equals(action)) {
                stopping = true;
                worker.execute(() -> {
                    try { if (client != null) client.callAttr("disconnect"); }
                    catch (Exception ignored) { }
                    stopSelf();
                });
            }
        }
        return START_NOT_STICKY;
    }

    void command(String action, String value, String text, String reply, boolean notify) {
        if (stopping || worker.isShutdown()) return;
        worker.execute(() -> {
            if (client == null) return;
            try {
                if ("connect".equals(action)) pendingToken = value;
                client.callAttr("command", action, value, text, reply, notify);
            } catch (Exception e) {
                pendingToken = null;
                fail("처리하지 못했습니다. 연결 상태를 확인하고 다시 시도하세요.");
            }
        });
    }

    private void update() {
        if (client == null || stopping) return;
        try {
            snapshot = client.callAttr("snapshot").toString();
            JSONObject data = new JSONObject(snapshot);
            if (data.optBoolean("connected") && pendingToken != null) {
                String token = pendingToken;
                pendingToken = null;
                try { TokenStore.save(this, token); }
                catch (Exception e) { fail("연결됨 · 토큰 저장 실패 (다음 실행 시 다시 입력)"); }
            } else if (!data.optBoolean("busy") && !data.optBoolean("connected")) {
                pendingToken = null;
            }
            String status = data.optString("status");
            if (!status.equals(lastStatus)) {
                lastStatus = status;
                getSystemService(NotificationManager.class).notify(1, notification(status));
            }
        } catch (Exception e) { fail("연결 상태를 읽지 못했습니다. 앱에서 다시 연결하세요."); }
    }

    private void fail(String message) {
        try {
            JSONObject data = new JSONObject(snapshot);
            data.put("status", message);
            snapshot = data.toString();
        } catch (Exception ignored) { }
    }

    @Override public void onDestroy() {
        instance = null;
        stopping = true;
        worker.execute(() -> {
            try { if (client != null) client.callAttr("disconnect"); }
            catch (Exception ignored) { }
        });
        worker.shutdown();
        super.onDestroy();
    }
    @Override public IBinder onBind(Intent intent) { return null; }
}
