package com.axicavlo.chatbot;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

public class MainActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<String, String> drafts = new HashMap<>();
    private EditText token, composer;
    private TextView status, replyLabel;
    private Spinner servers, channels;
    private LinearLayout messages;
    private ScrollView scroll;
    private Button connect, send;
    private CheckBox notifyReply;
    private String serverId = "", channelId = "", replyId = "", lastSnapshot = "", pendingText = "";
    private String serverRows = "", channelRows = "", messageRows = "";
    private List<String> serverIds = new ArrayList<>(), channelIds = new ArrayList<>();
    private long sent = -1;
    private boolean rendering;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            BotService service = BotService.instance;
            if (service != null && !service.snapshot.equals(lastSnapshot)) {
                lastSnapshot = service.snapshot;
                try { render(new JSONObject(lastSnapshot)); }
                catch (JSONException e) { status.setText("화면을 갱신하지 못했습니다."); }
            } else if (service == null) {
                status.setText("연결 종료 · 토큰을 입력해 연결하세요.");
                connect.setEnabled(true);
                send.setEnabled(false);
            }
            handler.postDelayed(this, 500);
        }
    };

    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density); }
    private Button button(String text, LinearLayout parent) {
        Button result = new Button(this); result.setText(text);
        if (parent.getOrientation() == LinearLayout.HORIZONTAL) {
            result.setMinWidth(0); result.setMinimumWidth(0); result.setTextSize(13);
            parent.addView(result, new LinearLayout.LayoutParams(0, -2, 1));
        } else parent.addView(result);
        return result;
    }
    private void command(String action, String value, String text, String reply, boolean notify) {
        BotService service = BotService.instance;
        if (service != null) service.command(action, value, text, reply, notify);
    }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(Color.rgb(0, 143, 165));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(12), dp(8), dp(12), dp(8));
        root.setBackgroundColor(Color.rgb(233, 238, 243));
        setContentView(root);
        // Respect status/navigation bars, including Android 15 edge-to-edge.
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(dp(12) + insets.getSystemWindowInsetLeft(), dp(8) + insets.getSystemWindowInsetTop(),
                dp(12) + insets.getSystemWindowInsetRight(), dp(8) + insets.getSystemWindowInsetBottom());
            return insets;
        });
        TextView title = new TextView(this);
        title.setText("채팅봇 " + BuildConfig.VERSION_NAME); title.setTextSize(23);
        title.setTextColor(Color.rgb(0, 143, 165)); root.addView(title);
        token = new EditText(this); token.setHint("봇 토큰"); token.setSingleLine(true);
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setSaveEnabled(false);
        if (Build.VERSION.SDK_INT >= 26) token.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        try { token.setText(TokenStore.load(this)); }
        catch (Exception e) { Toast.makeText(this, "저장된 토큰을 읽지 못했습니다. 다시 입력하세요.", Toast.LENGTH_LONG).show(); }
        root.addView(token);
        LinearLayout controls = new LinearLayout(this); root.addView(controls);
        connect = button("연결", controls);
        connect.setOnClickListener(v -> {
            String value = token.getText().toString().trim();
            if (value.isEmpty()) { token.setError("봇 토큰을 입력하세요."); return; }
            if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 10);
            }
            Intent intent = new Intent(this, BotService.class).setAction("connect").putExtra("token", value);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
            token.setText(""); connect.setEnabled(false); status.setText("연결 중…");
        });
        button("새로고침", controls).setOnClickListener(v -> command("refresh", "", "", "", false));
        button("종료", controls).setOnClickListener(v -> {
            if (BotService.instance != null) startService(new Intent(this, BotService.class).setAction("disconnect"));
        });
        button("토큰 삭제", controls).setOnClickListener(v -> { TokenStore.clear(this); token.setText(""); });
        status = new TextView(this); status.setText("봇 토큰을 입력하세요."); root.addView(status);
        servers = new Spinner(this); channels = new Spinner(this);
        root.addView(servers); root.addView(channels);
        servers.setOnItemSelectedListener(selection(() -> {
            int i = servers.getSelectedItemPosition();
            if (!rendering && i > 0 && i < serverIds.size() && !serverIds.get(i).equals(serverId)) {
                saveDraft(); serverId = serverIds.get(i); channelId = "";
                clearReply(); composer.setText("");
                command("server", serverId, "", "", false);
            }
        }));
        channels.setOnItemSelectedListener(selection(() -> {
            int i = channels.getSelectedItemPosition();
            if (!rendering && i > 0 && i < channelIds.size() && !channelIds.get(i).equals(channelId)) {
                saveDraft(); channelId = channelIds.get(i); clearReply();
                composer.setText(drafts.getOrDefault(channelId, ""));
                command("channel", channelId, "", "", false);
            }
        }));
        scroll = new ScrollView(this);
        messages = new LinearLayout(this); messages.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(messages); root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout replyBar = new LinearLayout(this); root.addView(replyBar);
        replyLabel = new TextView(this); replyBar.addView(replyLabel, new LinearLayout.LayoutParams(0, -2, 1));
        button("답장 취소", replyBar).setOnClickListener(v -> clearReply());
        notifyReply = new CheckBox(this); notifyReply.setText("답장 알림 보내기"); root.addView(notifyReply);
        composer = new EditText(this); composer.setHint("메시지 (길게 눌러 답장·멘션)");
        composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        composer.setMinLines(2); composer.setMaxLines(4); root.addView(composer);
        send = button("전송", root); send.setEnabled(false);
        send.setOnClickListener(v -> {
            String text = composer.getText().toString();
            if (!text.trim().isEmpty() && !channelId.isEmpty()) {
                pendingText = text;
                send.setEnabled(false);
                command("send", "", text, replyId, notifyReply.isChecked());
            }
        });
    }

    private AdapterView.OnItemSelectedListener selection(Runnable action) {
        return new AdapterView.OnItemSelectedListener() {
            public void onItemSelected(AdapterView<?> p, View v, int position, long id) { action.run(); }
            public void onNothingSelected(AdapterView<?> p) { }
        };
    }
    private void saveDraft() { if (!channelId.isEmpty()) drafts.put(channelId, composer.getText().toString()); }
    private void clearReply() { replyId = ""; replyLabel.setText(""); }
    private List<String> fill(Spinner spinner, JSONArray rows, String prompt, String selected) throws JSONException {
        List<String> ids = new ArrayList<>(), names = new ArrayList<>();
        ids.add(""); names.add(prompt);
        for (int i = 0; i < rows.length(); i++) {
            JSONArray row = rows.getJSONArray(i); ids.add(row.getString(0)); names.add(row.getString(1));
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, names);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item); spinner.setAdapter(adapter);
        spinner.setSelection(Math.max(0, ids.indexOf(selected)));
        return ids;
    }

    private void render(JSONObject state) throws JSONException {
        rendering = true;
        try {
            status.setText(state.optString("status"));
            connect.setEnabled(!state.optBoolean("busy"));
            String newServer = state.optString("server_id"), newChannel = state.optString("channel_id");
            if (!newChannel.equals(channelId)) {
                saveDraft(); clearReply(); channelId = newChannel;
                composer.setText(drafts.getOrDefault(channelId, ""));
            }
            serverId = newServer;
            JSONArray rows = state.optJSONArray("servers");
            if (rows != null && !rows.toString().equals(serverRows)) {
                serverRows = rows.toString(); serverIds = fill(servers, rows, "서버 선택", serverId);
            }
            rows = state.optJSONArray("channels");
            if (rows != null && !rows.toString().equals(channelRows)) {
                channelRows = rows.toString(); channelIds = fill(channels, rows, "채널 선택", channelId);
            }
            rows = state.optJSONArray("messages");
            if (rows != null && !rows.toString().equals(messageRows)) {
                boolean atBottom = scroll.getChildAt(0).getHeight() <= scroll.getHeight() + scroll.getScrollY() + dp(48);
                messageRows = rows.toString(); messages.removeAllViews();
                boolean replyExists = replyId.isEmpty();
                for (int i = 0; i < rows.length(); i++) {
                    JSONObject row = rows.getJSONObject(i);
                    if (replyId.equals(row.getString("id"))) replyExists = true;
                    TextView view = new TextView(this); view.setText(row.getString("text"));
                    view.setTextSize(15); view.setPadding(dp(10), dp(8), dp(10), dp(8));
                    view.setBackgroundColor(Color.WHITE);
                    LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.bottomMargin = dp(6);
                    messages.addView(view, params);
                    view.setOnLongClickListener(v -> { messageMenu(row); return true; });
                }
                if (!replyExists) clearReply();
                if (atBottom) scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            }
            long count = state.optLong("sent");
            if (sent >= 0 && count != sent) {
                if (composer.getText().toString().equals(pendingText)) composer.setText("");
                pendingText = ""; clearReply();
            }
            sent = count;
            send.setEnabled(state.optBoolean("connected") && !channelId.isEmpty());
        } finally { rendering = false; }
    }

    private void messageMenu(JSONObject row) {
        new AlertDialog.Builder(this).setItems(new String[]{"답장", "사용자 멘션", "복사"}, (dialog, which) -> {
            if (which == 0) {
                replyId = row.optString("id"); replyLabel.setText("답장: " + row.optString("author"));
            } else if (which == 1) {
                composer.getText().insert(Math.max(0, composer.getSelectionStart()), "<@" + row.optString("author_id") + "> ");
            } else {
                getSystemService(android.content.ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("메시지", row.optString("text")));
            }
        }).show();
    }
    @Override protected void onResume() {
        super.onResume(); lastSnapshot = ""; handler.post(poll);
        command("refresh", "", "", "", false);
    }
    @Override protected void onPause() { handler.removeCallbacks(poll); saveDraft(); super.onPause(); }
}
