"""各技术栈的 App/网站接入示例代码生成"""


def _head(base: str, app_id: str) -> str:
    return (
        "接口地址：%s\n"
        "App 标识：%s\n"
        "（标识不用改，照抄即可；换 App 时换这个标识就行）\n"
        "————————————————————\n\n"
    ) % (base, app_id)


def build_snippets(base: str, app_id: str) -> dict[str, str]:
    """返回 {技术栈: 代码文本}"""
    api_v = base + "/api/app/verify"
    api_c = base + "/api/app/check"

    kotlin = """// ========== 安卓原生（Kotlin）==========
// 1. build.gradle.kts 加依赖：
//    implementation("com.squareup.okhttp3:okhttp:4.12.0")
//    implementation("org.json:json:20240303")

import android.content.Context
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object Kami {

    // ↓↓↓ 只改这两行 ↓↓↓
    private const val BASE = "%(base)s"
    private const val APP_ID = "%(app_id)s"
    // ↑↑↑ 只改这两行 ↑↑↑

    private const val PREFS = "kami_prefs"
    private const val KEY_CODE = "kami_code"

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    // 读取本地保存的卡密
    fun savedCode(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_CODE, "").orEmpty()

    fun saveCode(ctx: Context, code: String) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY_CODE, code.trim().uppercase()).apply()
    }

    fun clearCode(ctx: Context) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().remove(KEY_CODE).apply()
    }

    data class Result(
        val ok: Boolean,
        val key: String,        // ok / invalid / expired / notyet / limit / rate / net
        val message: String,    // 中文说明
        val expireText: String  // 到期时间文字，永久为空
    )

    /** 首次激活：用户输入卡密时调用（会开始计时） */
    fun verify(ctx: Context, code: String, cb: (Result) -> Unit) =
        post("$BASE/api/app/verify", code, cb, onSuccess = { saveCode(ctx, code) })

    /** 每次启动校验：不激活、不扣时长 */
    fun check(code: String, cb: (Result) -> Unit) =
        post("$BASE/api/app/check", code, cb, onSuccess = {})

    /** 启动时一步到位：有卡密就校验，没有就要求输入 */
    fun gate(ctx: Context, onNeedInput: () -> Unit, onPass: (String) -> Unit) {
        val code = savedCode(ctx)
        if (code.isBlank()) { onNeedInput(); return }
        check(code) { r ->
            if (r.ok) onPass(r.expireText) else onNeedInput()
        }
        startGuard(ctx, onNeedInput)
    }

    /** 每 5 分钟复核一次；失效立即回调 onLock（锁回卡密输入页） */
    fun startGuard(ctx: Context, onLock: () -> Unit) {
        val timer = java.util.Timer("kami-guard", true)
        timer.schedule(object : java.util.TimerTask() {
            override fun run() {
                val code = savedCode(ctx)
                if (code.isBlank()) return
                check(code) { r ->
                    if (!r.ok) {
                        clearCode(ctx)
                        onLock()   // 卡密失效 → 锁定，要求重新输入
                    }
                }
            }
        }, 5 * 60 * 1000L, 5 * 60 * 1000L)
    }

    private fun post(url: String, code: String, cb: (Result) -> Unit, onSuccess: () -> Unit) {
        val body = JSONObject().put("code", code).put("app", APP_ID).toString()
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url(url)
            .post(body)
            .header("X-Kami-Code", code)
            .header("X-Kami-App", APP_ID)
            .build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                cb(Result(false, "net", "网络错误，请检查网络后重试", ""))
            }
            override fun onResponse(call: Call, resp: Response) {
                resp.use {
                    try {
                        val j = JSONObject(it.body?.string().orEmpty())
                        val r = Result(
                            j.optBoolean("ok", false),
                            j.optString("key", "invalid"),
                            j.optString("message", "卡密无效"),
                            j.optString("expire_text", "")
                        )
                        if (r.ok) onSuccess()
                        cb(r)
                    } catch (e: Exception) {
                        cb(Result(false, "net", "返回数据异常", ""))
                    }
                }
            }
        })
    }
}

// ========== 在界面里这样用 ==========
// 进入 App 时：
// Kami.gate(this,
//     onNeedInput = { showKeyDialog() },          // 没有卡密/已失效 → 弹输入框
//     onPass = { exp -> toast("有效，$exp") }      // 校验通过 → 进入主界面
// )
//
// 用户在输入框里填完卡密点确定：
// Kami.verify(this, input) { r ->
//     if (r.ok) { enterMain(); toast("已激活，${r.expireText}") }
//     else toast(r.message)   // 例如「卡密已过期」「卡密无效」
// }

"""

    java = """// ========== 安卓原生（Java）==========
// 1. build.gradle 加依赖：
//    implementation("com.squareup.okhttp3:okhttp:4.12.0")

import android.content.Context;
import okhttp3.*;
import org.json.JSONObject;

public class Kami {

    // ↓↓↓ 只改这两行 ↓↓↓
    private static final String BASE = "%(base)s";
    private static final String APP_ID = "%(app_id)s";
    // ↑↑↑ 只改这两行 ↑↑↑

    private static final String PREFS = "kami_prefs";
    private static final String KEY = "kami_code";
    private static final OkHttpClient HTTP = new OkHttpClient();
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");

    public interface Callback2 { void onResult(boolean ok, String key, String message, String expireText); }

    public static String saved(Context c) {
        return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "");
    }
    public static void save(Context c, String code) {
        c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
         .putString(KEY, code.trim().toUpperCase()).apply();
    }

    /** 首次激活 */
    public static void verify(Context c, String code, Callback2 cb) {
        post(BASE + "/api/app/verify", code, new Callback2() {
            public void onResult(boolean ok, String k, String m, String e) {
                if (ok) save(c, code);
                cb.onResult(ok, k, m, e);
            }
        });
    }

    /** 每次启动校验 */
    public static void check(String code, Callback2 cb) {
        post(BASE + "/api/app/check", code, cb);
    }

    /** 启动闸门：有卡密就校验，否则要求输入 */
    public static void gate(Context c, Runnable needInput, Callback2 pass) {
        String code = saved(c);
        if (code == null || code.trim().isEmpty()) { needInput.run(); return; }
        check(code, (ok, k, m, e) -> { if (ok) pass.onResult(true, k, m, e); else needInput.run(); });
        startGuard(c, needInput);
    }

    private static final java.util.concurrent.ScheduledExecutorService GUARD =
            java.util.concurrent.Executors.newSingleThreadScheduledExecutor();

    /** 每 5 分钟复核一次；失效立即回调 needInput（锁回卡密输入页） */
    public static void startGuard(Context c, Runnable needInput) {
        GUARD.scheduleAtFixedRate(() -> {
            String code = saved(c);
            if (code == null || code.trim().isEmpty()) return;
            check(code, (ok, k, m, e) -> {
                if (!ok) {
                    c.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(KEY).apply();
                    needInput.run();
                }
            });
        }, 5, 5, java.util.concurrent.TimeUnit.MINUTES);
    }

    private static void post(String url, String code, Callback2 cb) {
        String json = "{\\"code\\":\\"" + code + "\\",\\"app\\":\\"" + APP_ID + "\\"}";
        Request req = new Request.Builder()
                .url(url)
                .post(RequestBody.create(json, JSON))
                .header("X-Kami-Code", code)
                .header("X-Kami-App", APP_ID)
                .build();
        HTTP.newCall(req).enqueue(new okhttp3.Callback() {
            public void onFailure(Call call, java.io.IOException e) {
                cb.onResult(false, "net", "网络错误，请检查网络后重试", "");
            }
            public void onResponse(Call call, Response resp) throws java.io.IOException {
                try (Response r = resp) {
                    JSONObject j = new JSONObject(r.body().string());
                    cb.onResult(j.optBoolean("ok"), j.optString("key"), j.optString("message"), j.optString("expire_text"));
                } catch (Exception e) { cb.onResult(false, "net", "返回数据异常", ""); }
            }
        });
    }
}

// 用法：
// Kami.gate(this, () -> showKeyDialog(), (ok, k, m, e) -> enterMain());
// Kami.verify(this, input, (ok, k, m, e) -> { if (ok) enterMain(); else toast(m); });

"""

    flutter = """// ========== Flutter（Android / iOS 通用）==========
// pubspec.yaml 加：http: ^1.2.0   shared_preferences: ^2.2.0

import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Kami {
  // ↓↓↓ 只改这两行 ↓↓↓
  static const String base = '%(base)s';
  static const String appId = '%(app_id)s';
  // ↑↑↑ 只改这两行 ↑↑↑

  static const _key = 'kami_code';

  static Future<String?> savedCode() async {
    final sp = await SharedPreferences.getInstance();
    final v = sp.getString(_key);
    return (v == null || v.trim().isEmpty) ? null : v;
  }

  static Future<void> saveCode(String code) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString(_key, code.trim().toUpperCase());
  }

  static Future<void> clearCode() async {
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_key);
  }

  /// 首次激活（开始计时）
  static Future<Map> verify(String code) async {
    final r = await _post('/api/app/verify', code);
    if (r['ok'] == true) await saveCode(code);
    return r;
  }

  /// 每次启动校验（不激活、不扣时长）
  static Future<Map> check(String code) => _post('/api/app/check', code);

  static Future<Map> _post(String path, String code) async {
    try {
      final res = await http
          .post(
            Uri.parse('$base$path'),
            headers: {
              'Content-Type': 'application/json',
              'X-Kami-Code': code,
              'X-Kami-App': appId,
            },
            body: jsonEncode({'code': code, 'app': appId}),
          )
          .timeout(const Duration(seconds: 15));
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map;
    } catch (e) {
      return {'ok': false, 'key': 'net', 'message': '网络错误，请重试'};
    }
  }

  /// 启动闸门：返回 null 表示通过，返回字符串表示需要提示用户
  static Future<String?> gate() async {
    final code = await savedCode();
    if (code == null) return 'need_input';
    final r = await check(code);
    if (r['ok'] != true) return 'need_input';
    startGuard();   // 开始 5 分钟自动复核
    return null;
  }

  /// 每 5 分钟复核一次；失效立即回调 onLockCallback（锁回卡密输入页）
  static void startGuard() {
    Timer.periodic(const Duration(minutes: 5), (_) async {
      final code = await savedCode();
      if (code == null) return;
      final r = await check(code);
      if (r['ok'] != true) {
        await clearCode();
        onLockCallback?.call(r['message'] as String? ?? '卡密已失效');
      }
    });
  }

  /// 在启动页设置：Kami.onLockCallback = (msg) => 跳回卡密输入页;
  static void Function(String message)? onLockCallback;
}

// 用法（在启动页 initState 里）：
// final r = await Kami.gate();
// if (r == null) { goMain(); } else { showKeyDialog(); }
//
// 用户输入后：
// final res = await Kami.verify(input);
// if (res['ok'] == true) goMain(); else showTip(res['message']);

"""

    rn = """// ========== React Native ==========
// npm i @react-native-async-storage/async-storage

import AsyncStorage from '@react-native-async-storage/async-storage';

// ↓↓↓ 只改这两行 ↓↓↓
const BASE = '%(base)s';
const APP_ID = '%(app_id)s';
// ↑↑↑ 只改这两行 ↑↑↑

const KEY = 'kami_code';

export async function savedCode() {
  const v = await AsyncStorage.getItem(KEY);
  return v && v.trim() ? v : null;
}
export async function saveCode(code) {
  await AsyncStorage.setItem(KEY, code.trim().toUpperCase());
}
export async function clearCode() {
  await AsyncStorage.removeItem(KEY);
}

async function post(path, code) {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15000);
    const res = await fetch(BASE + path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Kami-Code': code,
        'X-Kami-App': APP_ID,
      },
      body: JSON.stringify({ code, app: APP_ID }),
      signal: ctl.signal,
    });
    clearTimeout(timer);
    return await res.json();
  } catch (e) {
    return { ok: false, key: 'net', message: '网络错误，请重试' };
  }
}

/** 首次激活 */
export async function verify(code) {
  const r = await post('/api/app/verify', code);
  if (r.ok) await saveCode(code);
  return r;
}

/** 每次启动校验 */
export function check(code) {
  return post('/api/app/check', code);
}

/** 启动闸门：返回 null 通过，'need_input' 需要用户输入 */
export async function gate() {
  const code = await savedCode();
  if (!code) return 'need_input';
  const r = await check(code);
  if (!r.ok) return 'need_input';
  startGuard();   // 开始 5 分钟自动复核
  return null;
}

/** 每 5 分钟复核一次；失效立即触发 onLock 回调（锁回卡密输入页） */
let lockHandler = null;
export function onLock(cb) { lockHandler = cb; }
export function startGuard() {
  setInterval(async () => {
    const code = await savedCode();
    if (!code) return;
    const r = await check(code);
    if (!r.ok) {
      await clearCode();
      if (lockHandler) lockHandler(r.message || '卡密已失效');
    }
  }, 5 * 60 * 1000);
}

// 用法：
// const r = await gate();
// if (r === null) navigation.replace('Home');
// else setShowInput(true);

"""

    ios = """// ========== iOS 原生（Swift 5+ / SwiftUI 或 UIKit 都行）==========

import Foundation

final class Kami {
    // ↓↓↓ 只改这两行 ↓↓↓
    static let base = "%(base)s"
    static let appId = "%(app_id)s"
    // ↑↑↑ 只改这两行 ↑↑↑

    static let keyName = "kami_code"

    static var savedCode: String? {
        let v = UserDefaults.standard.string(forKey: keyName)
        return (v?.isEmpty ?? true) ? nil : v
    }
    static func save(_ code: String) {
        UserDefaults.standard.set(code.trimmingCharacters(in: .whitespaces).uppercased(), forKey: keyName)
    }
    static func clear() { UserDefaults.standard.removeObject(forKey: keyName) }

    struct Result {
        let ok: Bool
        let key: String
        let message: String
        let expireText: String
    }

    static func post(_ path: String, code: String, completion: @escaping (Result) -> Void) {
        guard let url = URL(string: base + path) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 15
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(code, forHTTPHeaderField: "X-Kami-Code")
        req.setValue(appId, forHTTPHeaderField: "X-Kami-App")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["code": code, "app": appId])

        URLSession.shared.dataTask(with: req) { data, _, err in
            guard let data = data,
                  let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                DispatchQueue.main.async { completion(Result(ok: false, key: "net", message: "网络错误，请重试", expireText: "")) }
                return
            }
            let r = Result(
                ok: (j["ok"] as? Bool) ?? false,
                key: (j["key"] as? String) ?? "invalid",
                message: (j["message"] as? String) ?? "卡密无效",
                expireText: (j["expire_text"] as? String) ?? ""
            )
            DispatchQueue.main.async { completion(r) }
        }.resume()
    }

    /// 首次激活
    static func verify(_ code: String, completion: @escaping (Result) -> Void) {
        post("/api/app/verify", code: code) { r in
            if r.ok { save(code) }
            completion(r)
        }
    }

    /// 每次启动校验
    static func check(_ code: String, completion: @escaping (Result) -> Void) {
        post("/api/app/check", code: code, completion: completion)
    }

    /// 启动闸门
    static func gate(onPass: @escaping (String) -> Void, onNeedInput: @escaping () -> Void) {
        guard let code = savedCode else { onNeedInput(); return }
        check(code) { r in
            if r.ok {
                startGuard(onNeedInput: onNeedInput)
                onPass(r.expireText)
            } else {
                onNeedInput()
            }
        }
    }

    /// 每 5 分钟复核一次；失效立即 onNeedInput（锁回卡密输入页）
    static func startGuard(onNeedInput: @escaping () -> Void) {
        Timer.scheduledTimer(withTimeInterval: 5 * 60, repeats: true) { _ in
            guard let code = savedCode else { return }
            check(code) { r in
                if !r.ok {
                    clear()
                    onNeedInput()
                }
            }
        }
    }
}

// 用法：
// Kami.gate(onPass: { exp in showMain(exp) }, onNeedInput: { showKeyInput() })
// Kami.verify(input) { r in r.ok ? showMain(r.expireText) : showTip(r.message) }

"""

    webview = """// ========== 套壳网页 / WebView / 静态网站（最简单）==========
// 把下面这一行放进你的网页 <head> 或 <body> 里，弹窗会自动出现：

<script src="%(base)s/embed.js?site=%(app_id)s"></script>

// ————————————————————
// 如果是本地 HTML 打包进 App（离线套壳），也能用，只要用户能联网。
// 想自己控制界面而不使用自带弹窗，就在网页 JS 里这样调：

const BASE = '%(base)s';
const APP_ID = '%(app_id)s';

async function kamiVerify(code) {
  const res = await fetch(BASE + '/api/app/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Kami-Code': code, 'X-Kami-App': APP_ID },
    body: JSON.stringify({ code, app: APP_ID })
  });
  return res.json();   // { ok, key, message, expire_at, expire_text, days_left }
}

async function kamiCheck(code) {
  const res = await fetch(BASE + '/api/app/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Kami-Code': code, 'X-Kami-App': APP_ID },
    body: JSON.stringify({ code, app: APP_ID })
  });
  return res.json();
}

// 启动时：
// const saved = localStorage.getItem('kami_code');
// if (!saved) showInput(); else {
//   const r = await kamiCheck(saved);
//   if (r.ok) showContent(r.expire_text); else showInput(r.message);
// }

// 每 5 分钟自动复核：失效立即锁回卡密输入页（放在启动逻辑之后）
// setInterval(async () => {
//   const code = localStorage.getItem('kami_code');
//   if (!code) return;
//   const r = await kamiCheck(code);
//   if (!r.ok) {
//     localStorage.removeItem('kami_code');
//     showInput(r.message);   // 显示「卡密已过期/无效」，要求重新输入
//   }
// }, 5 * 60 * 1000);
//
// 切回页面时也立即复核（防止挂机绕过）：
// document.addEventListener('visibilitychange', async () => {
//   if (document.visibilityState !== 'visible') return;
//   const code = localStorage.getItem('kami_code');
//   if (!code) return;
//   const r = await kamiCheck(code);
//   if (!r.ok) { localStorage.removeItem('kami_code'); showInput(r.message); }
// });

"""

    csharp = """// ========== Windows 桌面 / C#（WinForms、WPF、.NET MAUI 通用）==========

using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

public static class Kami
{
    // ↓↓↓ 只改这两行 ↓↓↓
    private const string Base = "%(base)s";
    private const string AppId = "%(app_id)s";
    // ↑↑↑ 只改这两行 ↑↑↑

    private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };

    public static string SavedCode =>
        Properties.Settings.Default.KamiCode ?? "";   // 也可换成自己的配置文件

    public static void SaveCode(string code) { /* 保存到配置或文件 */ }

    public class Result
    {
        public bool ok { get; set; }
        public string key { get; set; } = "";
        public string message { get; set; } = "";
        public string expire_text { get; set; } = "";
        public int? days_left { get; set; }
    }

    private static async Task<Result> PostAsync(string path, string code)
    {
        try
        {
            var req = new HttpRequestMessage(HttpMethod.Post, Base + path);
            req.Headers.Add("X-Kami-Code", code);
            req.Headers.Add("X-Kami-App", AppId);
            req.Content = new StringContent(
                JsonSerializer.Serialize(new { code, app = AppId }),
                Encoding.UTF8, "application/json");

            var resp = await Http.SendAsync(req);
            var json = await resp.Content.ReadAsStringAsync();
            return JsonSerializer.Deserialize<Result>(json,
                new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
                ?? new Result { ok = false, message = "返回数据异常" };
        }
        catch
        {
            return new Result { ok = false, key = "net", message = "网络错误，请重试" };
        }
    }

    /// 首次激活
    public static async Task<Result> VerifyAsync(string code)
    {
        var r = await PostAsync("/api/app/verify", code);
        if (r.ok) SaveCode(code);
        return r;
    }

    /// 每次启动校验
    public static Task<Result> CheckAsync(string code) => PostAsync("/api/app/check", code);

    /// 每 5 分钟复核一次；失效立即 onLock（锁回卡密输入页）。主窗口 Loaded 时调用。
    public static async Task StartGuardAsync(Action<Result> onLock)
    {
        while (true)
        {
            await Task.Delay(TimeSpan.FromMinutes(5));
            var code = SavedCode;
            if (string.IsNullOrWhiteSpace(code)) continue;
            var r = await CheckAsync(code);
            if (!r.ok)
            {
                // 清除本地保存并锁定
                Properties.Settings.Default.KamiCode = "";
                Properties.Settings.Default.Save();
                onLock(r);
            }
        }
    }
}

// 用法：
// var r = await Kami.CheckAsync(Kami.SavedCode);
// if (!r.ok) ShowKeyDialog(); else ShowMain();

"""

    python = """# ========== Python 桌面 / 脚本（tkinter、PyQt 通用）==========
# pip install requests

import requests

# ↓↓↓ 只改这两行 ↓↓↓
BASE = "%(base)s"
APP_ID = "%(app_id)s"
# ↑↑↑ 只改这两行 ↑↑↑

TIMEOUT = 15


def _post(path, code):
    try:
        r = requests.post(
            BASE + path,
            json={"code": code, "app": APP_ID},
            headers={"X-Kami-Code": code, "X-Kami-App": APP_ID},
            timeout=TIMEOUT,
        )
        return r.json()
    except Exception:
        return {"ok": False, "key": "net", "message": "网络错误，请重试"}


def verify(code):
    \"\"\"首次激活（开始计时）\"\"\"
    res = _post("/api/app/verify", code)
    if res.get("ok"):
        _save(code)
    return res


def check(code):
    \"\"\"每次启动校验（不激活、不扣时长）\"\"\"
    return _post("/api/app/check", code)


def _save(code):
    with open(".kami", "w", encoding="utf-8") as f:
        f.write(code.strip().upper())


def _load():
    try:
        with open(".kami", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def gate():
    \"\"\"返回 True 表示通过，同时启动 5 分钟自动复核\"\"\"
    code = _load()
    if not code:
        return False
    if check(code).get("ok"):
        start_guard(on_lock=lambda msg: _lock(msg))
        return True
    return False


def _lock(msg):
    \"\"\"卡密失效：清除本地保存并退出主程序（或换成你的锁定界面）\"\"\"
    try:
        import os
        os.remove(".kami")
    except OSError:
        pass
    print("已锁定：", msg)
    raise SystemExit(1)


def start_guard(on_lock, interval=300):
    \"\"\"每 5 分钟复核一次；失效立即回调 on_lock(message)\"\"\"
    import threading, time

    def loop():
        while True:
            time.sleep(interval)
            code = _load()
            if not code:
                continue
            r = check(code)
            if not r.get("ok"):
                on_lock(r.get("message", "卡密已失效"))
                return

    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    if not gate():
        user_code = input("请输入卡密：").strip()
        res = verify(user_code)
        print(res.get("message"), res.get("expire_text", ""))
        if not res.get("ok"):
            raise SystemExit(1)
    print("已解锁，继续运行主程序...")

"""

    other = r"""# ========== 其他软件 / 通用方式 ==========
# 适用：AutoHotkey、按键精灵、易语言、Delphi、VB6、Go、PHP、Electron、
#       游戏插件、脚本工具、任何能发 HTTP 请求的软件

# ── 方式一：纯 HTTP 接口（最通用，任何软件都能调）──────────
# 首次激活（校验并开始计时）：
#   POST %(base)s/api/app/verify
#   Header: X-Kami-App: %(app_id)s
#   Header: X-Kami-Code: 用户输入的卡密
#   Header: X-Kami-Device: 本机唯一标识（可选但强烈建议）
#
# 之后每次启动复核（不重复计时，失效返回 ok=false）：
#   POST %(base)s/api/app/check
#   Header 同上
#
# 返回 JSON：
#   {"ok": true,  "key": "ok",     "message": "验证成功", "expire_text": "永久有效"}
#   {"ok": false, "key": "expired","message": "卡密已过期"}
#   {"ok": false, "key": "device", "message": "该卡密已绑定其他设备"}
#   key 取值：ok / invalid / expired / notyet / limit / device / rate / net
#
# ── 方式二：Windows 命令行（bat / AHK / 易语言 可直接调用）──
#   curl -s -X POST "%(base)s/api/app/verify" ^
#        -H "X-Kami-App: %(app_id)s" ^
#        -H "X-Kami-Code: 卡密" ^
#        -H "X-Kami-Device: %%COMPUTERNAME%%"
# 返回里出现 "ok":true 就是通过。
# 机器码用 %%COMPUTERNAME%%（电脑名）或 wmic csproduct get uuid 取硬件码。

# ── 方式三：参考实现（Go，编译成 exe 给任何程序调用）───────
package main

import (
    "bytes"; "encoding/json"; "fmt"; "net/http"; "os"; "os/exec"; "strings"; "time"
)

const baseURL = "%(base)s"
const appID   = "%(app_id)s"

func call(path, code, device string) map[string]interface{} {
    req, _ := http.NewRequest("POST", baseURL+path, bytes.NewBufferString(""))
    req.Header.Set("X-Kami-App", appID)
    req.Header.Set("X-Kami-Code", code)
    req.Header.Set("X-Kami-Device", device)
    c := &http.Client{Timeout: 15 * time.Second}
    resp, err := c.Do(req)
    if err != nil { return map[string]interface{}{"ok": false, "message": "网络错误"} }
    defer resp.Body.Close()
    var out map[string]interface{}
    json.NewDecoder(resp.Body).Decode(&out)
    return out
}

func deviceID() string {
    out, err := exec.Command("wmic", "csproduct", "get", "uuid").Output()
    if err != nil { return "unknown" }
    s := strings.Fields(string(out))
    if len(s) > 1 { return s[1] }
    return "unknown"
}

func main() {
    cfg := ".kami_code"
    data, _ := os.ReadFile(cfg)
    code := strings.TrimSpace(string(data))
    if code == "" {
        fmt.Print("请输入卡密：")
        fmt.Scanln(&code)
        r := call("/api/app/verify", code, deviceID())
        if r["ok"] != true { fmt.Println("卡密无效：", r["message"]); os.Exit(1) }
        os.WriteFile(cfg, []byte(strings.ToUpper(code)), 0600)
        fmt.Println("验证成功，已激活：", r["expire_text"])
        return
    }
    r := call("/api/app/check", code, deviceID())
    if r["ok"] != true {
        os.Remove(cfg)
        fmt.Println("卡密已失效，请重新输入：", r["message"])
        os.Exit(1)
    }
    fmt.Println("已解锁，到期：", r["expire_text"])
}
"""

    return {
        "Android · Kotlin": kotlin % {"base": base, "app_id": app_id},
        "Android · Java": java % {"base": base, "app_id": app_id},
        "Flutter": flutter % {"base": base, "app_id": app_id},
        "React Native": rn % {"base": base, "app_id": app_id},
        "iOS · Swift": ios % {"base": base, "app_id": app_id},
        "网页 / WebView 套壳": webview % {"base": base, "app_id": app_id},
        "Windows · C#": csharp % {"base": base, "app_id": app_id},
        "Python 桌面": python % {"base": base, "app_id": app_id},
        "其他软件 · 通用 HTTP": other % {"base": base, "app_id": app_id},
    }
