package com.axicavlo.chatbot;

import android.Manifest;
import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.*;
import android.text.InputType;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import org.json.*;
import java.util.*;

public class MainActivity extends Activity {
    private static final int ACCENT = Color.rgb(0, 143, 165), INK = Color.rgb(49, 75, 92);
    private enum Page { HOME, CHANNELS, CHAT }
    private Page page = Page.HOME;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Map<String, String> drafts = new HashMap<>();
    private final Map<String, String[]> replies = new HashMap<>();
    private final Map<String, String> serverNames = new HashMap<>(), channelNames = new HashMap<>();
    private EditText token, composer;
    private TextView status, replyLabel, channelTitle, chatTitle;
    private LinearLayout serverList, channelList, messages, replyBar, homePage, channelPage, chatPage;
    private ListView mentionList;
    private LinearLayout mentionPanel;
    private final List<String> mentionIds = new ArrayList<>();
    private int mentionStart = -1, mentionEnd = -1;
    private static final java.util.regex.Pattern MENTION = java.util.regex.Pattern.compile("(?:^|[\\s(])@([^\\s@<>,!?;:()\\[\\]{}]*)$");
    private ScrollView scroll;
    private Button connect, send, home;
    private JSONArray serverData = new JSONArray(), channelData = new JSONArray(), messageData = new JSONArray();
    private String serverId = "", channelId = "", replyId = "", replyName = "", lastSnapshot = "";
    private String serverRows = "", channelRows = "", messageRows = "", awaitingServer = "", awaitingChannel = "";
    private String pendingText = "", pendingReply = "", statusText = "", sendingStatus = "";
    private long sent = -1;
    private boolean connected, connecting, initialState = true, sending;
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            BotService service = BotService.instance;
            if (service != null && !service.snapshot.equals(lastSnapshot)) {
                lastSnapshot = service.snapshot;
                try { render(new JSONObject(lastSnapshot)); }
                catch (JSONException e) { setStatus("화면을 갱신하지 못했습니다."); }
            } else if (service == null) {
                connected = false; connecting = false; sending = false;
                connect.setEnabled(true); updateSend(); setStatus("연결 종료 · 홈에서 봇 토큰을 입력해 연결하세요.");
            }
            handler.postDelayed(this, 400);
        }
    };
    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density); }
    private LinearLayout column() {
        LinearLayout view = new LinearLayout(this); view.setOrientation(LinearLayout.VERTICAL); return view;
    }
    private GradientDrawable rounded(int color, int radius) {
        GradientDrawable shape = new GradientDrawable(); shape.setColor(color); shape.setCornerRadius(dp(radius)); return shape;
    }
    private TextView label(String text, int size) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(INK); return view;
    }
    private Button button(String text) {
        Button view = new Button(this); view.setText(text); view.setAllCaps(false); view.setTextSize(14);
        view.setMinWidth(0); view.setMinimumWidth(0); view.setTextColor(INK); return view;
    }
    private void command(String action, String value, String text, String reply) {
        BotService service = BotService.instance;
        if (service != null) service.command(action, value, text, reply);
    }
    private void setStatus(String text) { statusText = text; status.setText(text); }

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(ACCENT);
        LinearLayout root = column(); root.setBackgroundColor(Color.rgb(233, 238, 243)); root.setFocusableInTouchMode(true);
        setContentView(root);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                int bottom = Math.max(bars.bottom, insets.getInsets(WindowInsets.Type.ime()).bottom);
                view.setPadding(bars.left, bars.top, bars.right, bottom);
            } else view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        status = label("봇 토큰을 입력하세요.", 11); status.setPadding(dp(8), dp(2), dp(8), dp(2)); root.addView(status);
        LinearLayout workspace = new LinearLayout(this); root.addView(workspace, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout rail = column(); rail.setBackgroundColor(Color.rgb(244, 247, 250)); rail.setPadding(dp(5), dp(6), dp(5), dp(6));
        workspace.addView(rail, new LinearLayout.LayoutParams(dp(68), -1));
        home = button("⌂"); home.setTextSize(30); home.setContentDescription("홈 · 봇 토큰 입력");
        home.setBackgroundColor(Color.TRANSPARENT);
        rail.addView(home, new LinearLayout.LayoutParams(-1, dp(54))); home.setOnClickListener(v -> showHome());
        ScrollView railScroll = new ScrollView(this); serverList = column(); railScroll.addView(serverList);
        rail.addView(railScroll, new LinearLayout.LayoutParams(-1, 0, 1));
        Button refresh = button("↻"); refresh.setTextSize(25); refresh.setContentDescription("서버와 채널 새로고침");
        refresh.setBackgroundColor(Color.TRANSPARENT);
        rail.addView(refresh, new LinearLayout.LayoutParams(-1, dp(48)));
        refresh.setOnClickListener(v -> command("refresh", "", "", ""));
        View divider = new View(this); divider.setBackgroundColor(Color.rgb(220, 229, 235));
        workspace.addView(divider, new LinearLayout.LayoutParams(dp(1), -1));
        FrameLayout content = new FrameLayout(this); workspace.addView(content, new LinearLayout.LayoutParams(0, -1, 1));
        buildHome(content); buildChannels(content); buildChat(content); showPage(Page.HOME);
    }
    private void buildHome(FrameLayout content) {
        homePage = column(); homePage.setGravity(Gravity.CENTER_VERTICAL); homePage.setPadding(dp(16), dp(12), dp(16), dp(12));
        content.addView(homePage, new FrameLayout.LayoutParams(-1, -1));
        TextView title = label("채팅봇 " + BuildConfig.VERSION_NAME, 25); title.setTextColor(ACCENT); homePage.addView(title);
        TextView description = label("봇 계정으로 대화를 시작하세요.", 13);
        description.setPadding(0, dp(8), 0, dp(20)); homePage.addView(description);
        token = new EditText(this); token.setHint("봇 토큰"); token.setSingleLine(true); token.setSaveEnabled(false);
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        if (Build.VERSION.SDK_INT >= 26) token.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        loadToken(); homePage.addView(token, new LinearLayout.LayoutParams(-1, -2));
        connect = button("연결하기"); connect.setTextColor(Color.WHITE); connect.setBackground(rounded(ACCENT, 10));
        LinearLayout.LayoutParams connectParams = new LinearLayout.LayoutParams(-1, dp(48)); connectParams.topMargin = dp(12);
        homePage.addView(connect, connectParams); connect.setOnClickListener(v -> connectBot());
        LinearLayout controls = new LinearLayout(this); homePage.addView(controls);
        Button disconnect = button("연결 종료"), forget = button("토큰 삭제");
        controls.addView(disconnect, new LinearLayout.LayoutParams(0, dp(48), 1));
        controls.addView(forget, new LinearLayout.LayoutParams(0, dp(48), 1));
        disconnect.setOnClickListener(v -> {
            if (BotService.instance != null) startService(new Intent(this, BotService.class).setAction("disconnect"));
        });
        forget.setOnClickListener(v -> { TokenStore.clear(this); token.setText(""); });
    }
    private void loadToken() {
        try { token.setText(TokenStore.load(this)); }
        catch (Exception e) { Toast.makeText(this, "저장된 토큰을 읽지 못했습니다. 다시 입력하세요.", Toast.LENGTH_LONG).show(); }
    }
    private void connectBot() {
        String value = token.getText().toString().trim();
        if (value.isEmpty()) { token.setError("봇 토큰을 입력하세요."); return; }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 10);
        }
        saveDraft(); drafts.clear(); replies.clear(); serverId = ""; channelId = "";
        awaitingServer = ""; awaitingChannel = ""; serverData = new JSONArray(); channelData = new JSONArray(); messageData = new JSONArray();
        serverRows = ""; channelRows = ""; messageRows = ""; messages.removeAllViews(); channelList.removeAllViews(); serverList.removeAllViews();
        clearReply(); composer.setText(""); sending = false; sent = -1;
        Intent intent = new Intent(this, BotService.class).setAction("connect").putExtra("token", value);
        connecting = true; connected = false;
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(intent); else startService(intent);
        token.setText(""); connect.setEnabled(false); setStatus("연결 중…"); hideKeyboard();
    }
    private void buildChannels(FrameLayout content) {
        channelPage = column(); channelPage.setPadding(dp(12), dp(12), dp(12), 0);
        content.addView(channelPage, new FrameLayout.LayoutParams(-1, -1));
        channelTitle = label("서버를 선택하세요", 20); channelTitle.setTypeface(null, Typeface.BOLD); channelPage.addView(channelTitle);
        ScrollView listScroll = new ScrollView(this); channelList = column(); listScroll.addView(channelList);
        channelPage.addView(listScroll, new LinearLayout.LayoutParams(-1, 0, 1));
    }
    private void buildChat(FrameLayout content) {
        chatPage = column(); chatPage.setPadding(dp(8), dp(8), dp(8), dp(6));
        content.addView(chatPage, new FrameLayout.LayoutParams(-1, -1));
        chatTitle = label("", 18); chatTitle.setTypeface(null, Typeface.BOLD); chatTitle.setPadding(dp(4), 0, 0, dp(8)); chatPage.addView(chatTitle);
        scroll = new ScrollView(this); messages = column(); scroll.addView(messages);
        FrameLayout conversation = new FrameLayout(this);
        conversation.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        chatPage.addView(conversation, new LinearLayout.LayoutParams(-1, 0, 1));
        replyBar = column(); replyBar.setBackground(rounded(Color.rgb(222, 243, 246), 8));
        LinearLayout replyHeading = new LinearLayout(this); replyHeading.setGravity(Gravity.CENTER_VERTICAL); replyBar.addView(replyHeading);
        replyLabel = label("", 13); replyLabel.setPadding(dp(8), 0, 0, 0); replyLabel.setMaxLines(1);
        replyLabel.setEllipsize(android.text.TextUtils.TruncateAt.END);
        replyHeading.addView(replyLabel, new LinearLayout.LayoutParams(0, -2, 1));
        Button cancel = button("×"); cancel.setTextSize(20); cancel.setPadding(0, 0, 0, 0); cancel.setContentDescription("답장 취소");
        cancel.setBackgroundColor(Color.TRANSPARENT);
        replyHeading.addView(cancel, new LinearLayout.LayoutParams(dp(40), dp(40))); cancel.setOnClickListener(v -> clearReply());
        chatPage.addView(replyBar); replyBar.setVisibility(View.GONE);
        LinearLayout input = new LinearLayout(this); input.setGravity(Gravity.BOTTOM); input.setBackground(rounded(Color.WHITE, 10));
        chatPage.addView(input, new LinearLayout.LayoutParams(-1, -2));
        composer = new EditText(this) {
            @Override protected void onSelectionChanged(int start, int end) {
                super.onSelectionChanged(start, end);
                if (mentionList != null) post(() -> updateMentions());
            }
        };
        composer.setHint("메시지 (@로 멘션)"); composer.setTextSize(15);
        composer.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE); composer.setMinLines(1); composer.setMaxLines(4);
        input.addView(composer, new LinearLayout.LayoutParams(0, -2, 1));
        send = button("전송"); send.setPadding(0, 0, 0, 0); send.setTextColor(ACCENT); send.setEnabled(false);
        input.addView(send, new LinearLayout.LayoutParams(dp(52), dp(48))); send.setOnClickListener(v -> sendMessage());
        mentionPanel = column(); mentionPanel.setBackground(rounded(Color.WHITE, 10));
        mentionPanel.setPadding(dp(8), dp(6), dp(8), dp(6)); mentionPanel.setElevation(dp(6));
        TextView mentionHeading = label("멘션할 사용자", 12); mentionHeading.setTextColor(Color.rgb(113, 132, 147));
        mentionHeading.setPadding(dp(8), dp(4), dp(8), dp(6)); mentionPanel.addView(mentionHeading);
        mentionList = new ListView(this); mentionList.setBackgroundColor(Color.TRANSPARENT);
        mentionList.setDivider(new android.graphics.drawable.ColorDrawable(Color.rgb(237, 243, 246)));
        mentionList.setDividerHeight(dp(1));
        mentionList.setSelector(new android.graphics.drawable.ColorDrawable(Color.rgb(222, 243, 246)));
        mentionList.setVisibility(View.GONE); mentionList.setContentDescription("멘션 사용자 목록");
        mentionPanel.addView(mentionList, new LinearLayout.LayoutParams(-1, dp(144)));
        FrameLayout.LayoutParams overlay = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        overlay.setMargins(dp(4), dp(4), dp(4), dp(8)); conversation.addView(mentionPanel, overlay);
        mentionPanel.setVisibility(View.GONE);
        mentionList.setOnItemClickListener((parent, view, position, id) -> selectMention(position));
        composer.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            public void onTextChanged(CharSequence s, int start, int before, int count) { }
            public void afterTextChanged(Editable value) { updateMentions(); }
        });
        composer.setOnFocusChangeListener((view, focused) -> { if (focused) updateMentions(); else hideMentions(); });
    }
    private void showPage(Page next) {
        page = next; homePage.setVisibility(next == Page.HOME ? View.VISIBLE : View.GONE);
        channelPage.setVisibility(next == Page.CHANNELS ? View.VISIBLE : View.GONE);
        chatPage.setVisibility(next == Page.CHAT ? View.VISIBLE : View.GONE);
        home.setTextColor(next == Page.HOME ? ACCENT : INK);
        if (next != Page.CHAT) { hideMentions(); hideKeyboard(); }
    }
    private void showHome() { saveDraft(); if (token.getText().length() == 0) loadToken(); showPage(Page.HOME); }
    private void hideKeyboard() {
        View focus = getCurrentFocus();
        if (focus != null) { getSystemService(InputMethodManager.class).hideSoftInputFromWindow(focus.getWindowToken(), 0); focus.clearFocus(); }
    }
    private void openServer(String id) {
        saveDraft(); showPage(Page.CHANNELS);
        if (!id.equals(serverId)) {
            serverId = id; channelId = ""; awaitingServer = id; awaitingChannel = "";
            channelData = new JSONArray(); channelRows = ""; messages.removeAllViews(); messageRows = "";
            composer.setText(""); clearReply(); sending = false; command("server", id, "", "");
        } else command("refresh", "", "", "");
        renderServers(); renderChannels();
    }
    private void openChannel(String id) {
        saveDraft();
        if (!id.equals(channelId)) {
            channelId = id; awaitingChannel = id; messageData = new JSONArray(); messageRows = "";
            messages.removeAllViews(); sending = false; restoreDraft();
        }
        chatTitle.setText(channelNames.getOrDefault(id, "채팅방")); showPage(Page.CHAT);
        command("channel", id, "", ""); updateSend(); scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }
    private void saveDraft() {
        if (composer == null || channelId.isEmpty()) return;
        drafts.put(channelId, composer.getText().toString());
        if (replyId.isEmpty()) replies.remove(channelId);
        else replies.put(channelId, new String[]{replyId, replyName});
    }
    private void restoreDraft() {
        composer.setText(drafts.getOrDefault(channelId, ""));
        String[] reply = replies.get(channelId); clearReply();
        if (reply != null) setReply(reply[0], reply[1]);
    }
    private void clearReply() {
        replyId = ""; replyName = ""; replyLabel.setText(""); replyBar.setVisibility(View.GONE);
        if (!channelId.isEmpty()) replies.remove(channelId);
    }
    private void setReply(String id, String name) {
        replyId = id; replyName = name; replyLabel.setText("답장: " + name); replyBar.setVisibility(View.VISIBLE);
    }
    private void renderServers() {
        serverList.removeAllViews(); serverNames.clear();
        for (int i = 0; i < serverData.length(); i++) {
            JSONArray row = serverData.optJSONArray(i); if (row == null) continue;
            String id = row.optString(0), name = row.optString(1); serverNames.put(id, name);
            Button item = button(name); item.setTextSize(12); item.setMaxLines(2); item.setPadding(dp(2), 0, dp(2), 0);
            item.setContentDescription("서버: " + name); item.setTextColor(id.equals(serverId) ? Color.WHITE : INK);
            item.setBackground(rounded(id.equals(serverId) ? ACCENT : Color.rgb(220, 229, 235), 17));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, dp(54)); params.topMargin = dp(8);
            serverList.addView(item, params); item.setOnClickListener(v -> openServer(id));
        }
    }
    private void renderChannels() {
        channelList.removeAllViews(); channelNames.clear(); channelTitle.setText(serverNames.getOrDefault(serverId, "서버를 선택하세요"));
        if (channelData.length() == 0) {
            TextView empty = label(serverId.isEmpty() ? "왼쪽에서 서버를 선택하세요." : "표시할 채널이 없습니다. 새로고침을 눌러주세요.", 14);
            empty.setPadding(0, dp(20), 0, 0); channelList.addView(empty);
        }
        for (int i = 0; i < channelData.length(); i++) {
            JSONArray row = channelData.optJSONArray(i); if (row == null) continue;
            String id = row.optString(0), name = row.optString(1); channelNames.put(id, name);
            Button item = button(name); item.setGravity(Gravity.START | Gravity.CENTER_VERTICAL); item.setMinHeight(dp(52));
            item.setTextColor(id.equals(channelId) ? ACCENT : INK); item.setMaxLines(3);
            channelList.addView(item, new LinearLayout.LayoutParams(-1, -2)); item.setOnClickListener(v -> openChannel(id));
        }
    }
    private void render(JSONObject state) throws JSONException {
        setStatus(state.optString("status")); connected = state.optBoolean("connected"); connect.setEnabled(!state.optBoolean("busy"));
        if (connecting && connected) { connecting = false; showPage(Page.CHANNELS); }
        else if (initialState && connected) showPage(Page.CHANNELS);
        initialState = false;
        // Ignore snapshots queued before the latest navigation command.
        if ((!awaitingServer.isEmpty() && !awaitingServer.equals(state.optString("server_id")))
                || (!awaitingChannel.isEmpty() && !awaitingChannel.equals(state.optString("channel_id")))) return;
        awaitingServer = ""; awaitingChannel = "";
        String newServer = state.optString("server_id"), newChannel = state.optString("channel_id"); boolean serverChanged = !newServer.equals(serverId);
        if (!newChannel.equals(channelId)) {
            saveDraft(); channelId = newChannel; restoreDraft(); sending = false;
            if (page == Page.CHAT && channelId.isEmpty()) showPage(Page.CHANNELS);
        }
        serverId = newServer;
        JSONArray rows = state.optJSONArray("servers");
        if (rows != null && (!rows.toString().equals(serverRows) || serverChanged)) { serverRows = rows.toString(); serverData = rows; renderServers(); }
        rows = state.optJSONArray("channels");
        if (rows != null && (!rows.toString().equals(channelRows) || serverChanged)) { channelRows = rows.toString(); channelData = rows; renderChannels(); }
        rows = state.optJSONArray("messages");
        if (rows != null && !rows.toString().equals(messageRows)) { messageRows = rows.toString(); messageData = rows; renderMessages(); }
        long count = state.optLong("sent");
        if (sending && sent >= 0 && count != sent) {
            if (composer.getText().toString().equals(pendingText)) composer.setText("");
            if (replyId.equals(pendingReply)) clearReply(); sending = false; pendingText = ""; saveDraft();
        } else if (sending && !statusText.equals(sendingStatus) && !statusText.startsWith("연결됨")) sending = false;
        sent = count; updateSend();
    }
    private void renderMessages() throws JSONException {
        boolean atBottom = messages.getHeight() <= scroll.getHeight() + scroll.getScrollY() + dp(48);
        messages.removeAllViews(); boolean replyExists = replyId.isEmpty();
        for (int i = 0; i < messageData.length(); i++) {
            JSONObject row = messageData.getJSONObject(i); if (replyId.equals(row.getString("id"))) replyExists = true;
            TextView view = label(row.getString("text"), 14); view.setPadding(dp(10), dp(8), dp(10), dp(8)); view.setBackground(rounded(Color.WHITE, 10));
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2); params.bottomMargin = dp(6);
            messages.addView(view, params); view.setOnLongClickListener(v -> { messageMenu(row); return true; });
        }
        if (!replyExists) clearReply(); if (atBottom) scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
    }
    private void updateSend() { send.setEnabled(connected && !channelId.isEmpty() && !sending); }
    private void sendMessage() {
        String text = composer.getText().toString(); if (sending || !connected || text.trim().isEmpty() || channelId.isEmpty()) return;
        pendingText = text; pendingReply = replyId; sendingStatus = statusText; sending = true; updateSend();
        command("send", "", text, replyId);
    }
    private void insertMention(String id) {
        composer.getText().insert(Math.max(0, composer.getSelectionStart()), "<@" + id + "> "); composer.requestFocus();
        getSystemService(InputMethodManager.class).showSoftInput(composer, InputMethodManager.SHOW_IMPLICIT);
    }
    private void hideMentions() {
        mentionPanel.setVisibility(View.GONE); mentionList.setVisibility(View.GONE);
        mentionIds.clear(); mentionStart = -1; mentionEnd = -1;
    }
    private void updateMentions() {
        int end = composer.getSelectionStart();
        if (page != Page.CHAT || !composer.hasFocus() || end < 0 || end != composer.getSelectionEnd()) { hideMentions(); return; }
        String prefix = composer.getText().subSequence(0, end).toString();
        java.util.regex.Matcher match = MENTION.matcher(prefix);
        if (!match.find()) { hideMentions(); return; }
        String query = match.group(1).toLowerCase(Locale.ROOT);
        Map<String, String> users = new LinkedHashMap<>();
        for (int i = 0; i < messageData.length(); i++) {
            JSONObject row = messageData.optJSONObject(i); if (row != null) users.put(row.optString("author_id"), row.optString("author"));
        }
        mentionIds.clear(); List<String> names = new ArrayList<>();
        List<Map.Entry<String, String>> ordered = new ArrayList<>(users.entrySet());
        ordered.sort(Comparator.comparing(entry -> entry.getValue().toLowerCase(Locale.ROOT)));
        for (Map.Entry<String, String> user : ordered) {
            if ((user.getValue() + " " + user.getKey()).toLowerCase(Locale.ROOT).contains(query)) {
                mentionIds.add(user.getKey()); names.add(user.getValue());
            }
        }
        if (names.isEmpty()) { hideMentions(); return; }
        mentionStart = match.start(1) - 1; mentionEnd = end;
        mentionList.setAdapter(new ArrayAdapter<String>(this, android.R.layout.simple_list_item_1, names) {
            @Override public View getView(int position, View reusable, ViewGroup parent) {
                TextView row = (TextView) super.getView(position, reusable, parent);
                row.setTextColor(INK); row.setTextSize(15); row.setMinHeight(dp(48));
                row.setPadding(dp(12), dp(10), dp(12), dp(10)); return row;
            }
        });
        mentionList.getLayoutParams().height = dp(48 * Math.min(3, names.size()));
        mentionList.setVisibility(View.VISIBLE); mentionPanel.setVisibility(View.VISIBLE);
        mentionPanel.bringToFront(); mentionList.requestLayout();
    }
    private void selectMention(int position) {
        if (position < 0 || position >= mentionIds.size() || mentionStart < 0) return;
        String id = mentionIds.get(position); int start = mentionStart, end = mentionEnd;
        String replacement = "<@" + id + "> ";
        composer.getText().replace(start, end, replacement); composer.setSelection(start + replacement.length());
        hideMentions(); composer.requestFocus();
    }
    private void messageMenu(JSONObject row) {
        new AlertDialog.Builder(this).setItems(new String[]{"답장", "사용자 멘션", "복사"}, (dialog, which) -> {
            if (which == 0) { setReply(row.optString("id"), row.optString("author")); composer.requestFocus(); }
            else if (which == 1) insertMention(row.optString("author_id"));
            else getSystemService(ClipboardManager.class).setPrimaryClip(ClipData.newPlainText("메시지", row.optString("text")));
        }).show();
    }
    @Override public void onBackPressed() {
        if (page == Page.CHAT) { saveDraft(); showPage(Page.CHANNELS); renderChannels(); }
        else if (page == Page.CHANNELS) showHome(); else super.onBackPressed();
    }
    @Override protected void onResume() { super.onResume(); lastSnapshot = ""; handler.post(poll); command("refresh", "", "", ""); }
    @Override protected void onPause() { handler.removeCallbacks(poll); saveDraft(); super.onPause(); }
}
