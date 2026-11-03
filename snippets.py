"""各技术栈的 App/网站接入示例代码生成（v2 完整教程版）

要点：
- 每个技术栈都带「稳定设备号」，重启/关闭软件不会变，设备限制才能正常工作
- 首次激活 verify → 存卡密 → 后续启动 check 复核 → 每 5 分钟自动复核
- 代码里的接口地址和 App 标识已自动填好，复制即可用
"""


def _head(base: str, app_id: str) -> str:
    return (
        "接口地址：%s\n"
        "App 标识：%s\n"
        "（标识不用改，照抄即可；换 App 时换这个标识就行）\n"
        "————————————————————\n\n"
    ) % (base, app_id)


COMMON_FAQ = """
────────────────────────────────────────
【常见问题】
Q: 提示「此卡密已在其他设备使用」？
A: 一张卡密默认只能绑 1 台设备。换了手机/电脑就会这样。
   后台「批量生成卡密 → 设备限制」可以改成 2 台 / 3 台 / 不限。

Q: 用户换手机（同一人）想继续用？
A: 后台把该卡密的「设备限制」改成不限，或重新发一张新卡密。

Q: 提示「网络错误」？
A: 检查：① 手机/电脑能否上网；② 接口地址是否 https；
   ③ 安卓是否漏了 INTERNET 权限；④ 是否被防火墙拦。

Q: 为什么每次启动都要 check？
A: check 不扣时长、不重复计时，只确认卡密还有效；
   卡密被删/过期时能让软件立刻锁上，避免一直白用。

Q: 用户改系统时间能绕过吗？
A: 不能。有效期在服务器上算，客户端只看返回的 expire_at。

Q: 能防破解吗？
A: 任何客户端校验都能被逆向。建议关键逻辑放服务端，
   或配合签名校验/加壳。卡密系统只能挡住普通用户。
────────────────────────────────────────
"""


def build_snippets(base: str, app_id: str) -> dict[str, str]:
    """返回 {技术栈: 完整教程 + 代码}"""
    api_v = base + "/api/app/verify"
    api_c = base + "/api/app/check"

    # ================= Android Kotlin =================
    kotlin = """// ============================================================
//  安卓原生接入（Kotlin）— 完整可用代码
// ============================================================
// 【第 1 步】build.gradle.kts 加依赖：
//     implementation("com.squareup.okhttp3:okhttp:4.12.0")
//
// 【第 2 步】AndroidManifest.xml 加网络权限（漏了一定报网络错误）：
//     <uses-permission android:name="android.permission.INTERNET"/>
//
// 【第 3 步】把下面整个 Kami.kt 复制进项目
// 【第 4 步】MainActivity 里：
//     Kami.init(this)                      // 必须最先调用
//     Kami.gate(
//         onPass = { showMain() },         // 验证通过
//         onNeedInput = { showKeyInput() } // 需要输卡密
//     )
// ============================================================

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
    private const val KEY_DEV = "kami_device"

    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private var ctxRef: Context? = null

    /** 必须在 Application 或 Activity onCreate 里最先调用 */
    fun init(ctx: Context) {
        ctxRef = ctx.applicationContext
        deviceId()
    }

    /** 设备唯一标识：系统级 ANDROID_ID，重启/卸载重装都不变 */
    fun deviceId(): String {
        val sp = ctxRef?.getSharedPreferences(PREFS, Context.MODE_PRIVATE) ?: return "unknown"
        sp.getString(KEY_DEV, null)?.let { return it }
        val id = try {
            android.provider.Settings.Secure.getString(
                ctxRef!!.contentResolver,
                android.provider.Settings.Secure.ANDROID_ID
            ) ?: ""
        } catch (e: Exception) { "" }
        val v = if (id.isNotEmpty()) id else "kt-" + java.util.UUID.randomUUID().toString()
        sp.edit().putString(KEY_DEV, v).apply()
        return v
    }

    fun savedCode(): String? {
        val v = ctxRef?.getSharedPreferences(PREFS, Context.MODE_PRIVATE)?.getString(KEY_CODE, null)
        return if (v.isNullOrBlank()) null else v
    }

    private fun saveCode(code: String) {
        ctxRef?.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            ?.edit()?.putString(KEY_CODE, code.trim().uppercase())?.apply()
    }

    private fun clearCode() {
        ctxRef?.getSharedPreferences(PREFS, Context.MODE_PRIVATE)?.edit()?.remove(KEY_CODE)?.apply()
    }

    data class Result(val ok: Boolean, val key: String, val message: String, val expireText: String)

    private fun post(path: String, code: String, cb: (Result) -> Unit) {
        val body = JSONObject()
            .put("code", code)
            .put("app", APP_ID)
            .put("device", deviceId())
            .toString()
            .toRequestBody("application/json".toMediaType())
        val req = Request.Builder()
            .url(BASE + path)
            .post(body)
            .header("X-Kami-Code", code)
            .header("X-Kami-App", APP_ID)
            .header("X-Kami-Device", deviceId())
            .build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: java.io.IOException) {
                cb(Result(false, "net", "网络错误，请检查网络后重试", ""))
            }
            override fun onResponse(call: Call, resp: Response) {
                resp.use {
                    try {
                        val j = JSONObject(it.body?.string().orEmpty())
                        cb(Result(
                            j.optBoolean("ok", false),
                            j.optString("key", "invalid"),
                            j.optString("message", "卡密无效"),
                            j.optString("expire_text", "")
                        ))
                    } catch (e: Exception) {
                        cb(Result(false, "net", "返回数据异常", ""))
                    }
                }
            }
        })
    }

    /** 首次激活（开始计时），成功后自动保存卡密 */
    fun verify(code: String, cb: (Result) -> Unit) {
        post("/api/app/verify", code.trim().uppercase()) { r ->
            if (r.ok) saveCode(code)
            cb(r)
        }
    }

    /** 每次启动复核（不重复计时） */
    fun check(code: String, cb: (Result) -> Unit) = post("/api/app/check", code)

    /** 启动闸门：有卡密则复核通过放行，否则要求输入 */
    fun gate(onPass: () -> Unit, onNeedInput: () -> Unit) {
        val code = savedCode()
        if (code == null) { onNeedInput(); return }
        check(code) { r ->
            if (r.ok) {
                onPass()
                startGuard(onNeedInput)
            } else {
                clearCode()
                onNeedInput()
            }
        }
    }

    private var guardTimer: java.util.Timer? = null

    /** 每 5 分钟复核，失效清卡密并锁回去 */
    fun startGuard(onLock: () -> Unit, intervalMs: Long = 5 * 60 * 1000L) {
        guardTimer?.cancel()
        guardTimer = java.util.Timer().apply {
            scheduleAtFixedRate(object : java.util.TimerTask() {
                override fun run() {
                    val code = savedCode() ?: return
                    check(code) { r ->
                        if (!r.ok) {
                            clearCode()
                            android.os.Handler(android.os.Looper.getMainLooper())
                                .post { onLock() }
                            cancel()
                        }
                    }
                }
            }, intervalMs, intervalMs)
        }
    }
}
"""

    # ================= Android Java =================
    java = """// ============================================================
//  安卓原生接入（Java）— 完整可用代码
// ============================================================
// 【第 1 步】build.gradle 加依赖：
//     implementation 'com.squareup.okhttp3:okhttp:4.12.0'
//
// 【第 2 步】AndroidManifest.xml 加网络权限：
//     <uses-permission android:name="android.permission.INTERNET"/>
//
// 【第 3 步】复制下面整个 Kami.java
// 【第 4 步】MainActivity.onCreate 里：
//     Kami.init(this);
//     Kami.gate(() -> showMain(), () -> showKeyInput());
// ============================================================

import android.content.Context;
import android.content.SharedPreferences;
import okhttp3.*;

public class Kami {

    // ↓↓↓ 只改这两行 ↓↓↓
    private static final String BASE = "%(base)s";
    private static final String APP_ID = "%(app_id)s";
    // ↑↑↑ 只改这两行 ↑↑↑

    private static final String PREFS = "kami_prefs";
    private static final String KEY_CODE = "kami_code";
    private static final String KEY_DEV = "kami_device";
    private static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");

    private static final OkHttpClient HTTP = new OkHttpClient.Builder()
            .connectTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .build();

    private static Context ctx;
    private static volatile String DEVICE = "unknown";

    public interface Cb { void onResult(boolean ok, String key, String message, String expireText); }
    public interface Done { void run(); }

    /** 必须最先调用 */
    public static void init(Context c) {
        ctx = c.getApplicationContext();
        deviceId();
    }

    /** 设备唯一标识：系统 ANDROID_ID，重启/重装都不变 */
    public static String deviceId() {
        if (!"unknown".equals(DEVICE)) return DEVICE;
        SharedPreferences sp = sp();
        String v = sp == null ? null : sp.getString(KEY_DEV, null);
        if (v != null && !v.isEmpty()) { DEVICE = v; return v; }
        String id = "";
        try {
            id = android.provider.Settings.Secure.getString(
                    ctx.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        } catch (Exception ignored) {}
        if (id == null || id.isEmpty()) id = "jv-" + java.util.UUID.randomUUID().toString();
        if (sp != null) sp.edit().putString(KEY_DEV, id).apply();
        DEVICE = id;
        return id;
    }

    private static SharedPreferences sp() {
        return ctx == null ? null : ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static String savedCode() {
        SharedPreferences s = sp();
        String v = s == null ? null : s.getString(KEY_CODE, null);
        return (v == null || v.trim().isEmpty()) ? null : v;
    }
    private static void saveCode(String code) {
        SharedPreferences s = sp();
        if (s != null) s.edit().putString(KEY_CODE, code.trim().toUpperCase()).apply();
    }
    private static void clearCode() {
        SharedPreferences s = sp();
        if (s != null) s.edit().remove(KEY_CODE).apply();
    }

    private static void post(String path, String code, Cb cb) {
        String body = "{\\"code\\":\\"" + code + "\\",\\"app\\":\\"" + APP_ID
                + "\\",\\"device\\":\\"" + deviceId() + "\\"}";
        Request req = new Request.Builder()
                .url(BASE + path)
                .post(RequestBody.create(body, JSON))
                .header("X-Kami-Code", code)
                .header("X-Kami-App", APP_ID)
                .header("X-Kami-Device", deviceId())
                .build();
        HTTP.newCall(req).enqueue(new okhttp3.Callback() {
            @Override public void onFailure(Call call, java.io.IOException e) {
                cb.onResult(false, "net", "网络错误，请检查网络后重试", "");
            }
            @Override public void onResponse(Call call, Response resp) {
                try (Response r = resp) {
                    org.json.JSONObject j = new org.json.JSONObject(r.body().string());
                    cb.onResult(j.optBoolean("ok"), j.optString("key"),
                            j.optString("message"), j.optString("expire_text"));
                } catch (Exception e) {
                    cb.onResult(false, "net", "返回数据异常", "");
                }
            }
        });
    }

    /** 首次激活（开始计时） */
    public static void verify(String code, Cb cb) {
        post("/api/app/verify", code.trim().toUpperCase(), (ok, k, m, e) -> {
            if (ok) saveCode(code);
            cb.onResult(ok, k, m, e);
        });
    }

    /** 每次启动复核（不重复计时） */
    public static void check(String code, Cb cb) { post("/api/app/check", code, cb); }

    /** 启动闸门 */
    public static void gate(Done onPass, Done onNeedInput) {
        String code = savedCode();
        if (code == null) { onNeedInput.run(); return; }
        check(code, (ok, k, m, e) -> {
            if (ok) { onPass.run(); startGuard(onNeedInput); }
            else { clearCode(); onNeedInput.run(); }
        });
    }

    private static java.util.concurrent.ScheduledExecutorService guard;

    /** 每 5 分钟复核，失效锁回 */
    public static void startGuard(final Done onLock) {
        stopGuard();
        guard = java.util.concurrent.Executors.newSingleThreadScheduledExecutor();
        guard.scheduleAtFixedRate(new Runnable() {
            @Override public void run() {
                String code = savedCode();
                if (code == null) return;
                check(code, (ok, k, m, e) -> {
                    if (!ok) { clearCode(); onLock.run(); stopGuard(); }
                });
            }
        }, 5, 5, java.util.concurrent.TimeUnit.MINUTES);
    }

    public static void stopGuard() {
        if (guard != null) { guard.shutdownNow(); guard = null; }
    }
}
"""

    # ================= Flutter =================
    flutter = """// ============================================================
//  Flutter 接入 — 完整可用代码
// ============================================================
// 【第 1 步】加依赖：
//     flutter pub add http shared_preferences
//
// 【第 2 步】复制下面整个 kami.dart 到 lib/ 下
// 【第 3 步】程序入口：
//     void main() async {
//       WidgetsFlutterBinding.ensureInitialized();
//       await Kami.deviceId();          // 预初始化设备号
//       runApp(const MyApp());
//     }
// 【第 4 步】首页 initState：
//     final msg = await Kami.gate(onLock: () => setState(() => locked = true));
//     if (msg != null) showKeyInput(msg);
// ============================================================

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class Kami {
  // ↓↓↓ 只改这两行 ↓↓↓
  static const String base = "%(base)s";
  static const String appId = "%(app_id)s";
  // ↑↑↑ 只改这两行 ↑↑↑

  static const String _keyCode = 'kami_code';
  static const String _keyDev = 'kami_device';
  static String _devCache = '';

  /// 设备唯一标识：首次生成后存本地，重启不丢
  static Future<String> deviceId() async {
    if (_devCache.isNotEmpty) return _devCache;
    final sp = await SharedPreferences.getInstance();
    var v = sp.getString(_keyDev);
    if (v == null || v.isEmpty) {
      v = 'fl-${Platform.operatingSystem}-${DateTime.now().microsecondsSinceEpoch}'
          '-${Random().nextInt(999999)}';
      await sp.setString(_keyDev, v);
    }
    _devCache = v;
    return v;
  }

  static Future<String?> savedCode() async {
    final sp = await SharedPreferences.getInstance();
    final v = sp.getString(_keyCode);
    return (v == null || v.trim().isEmpty) ? null : v;
  }

  static Future<void> _saveCode(String code) async {
    final sp = await SharedPreferences.getInstance();
    await sp.setString(_keyCode, code.trim().toUpperCase());
  }

  static Future<void> clearCode() async {
    final sp = await SharedPreferences.getInstance();
    await sp.remove(_keyCode);
  }

  static Future<Map> _post(String path, String code) async {
    try {
      final dev = await deviceId();
      final res = await http
          .post(
            Uri.parse('$base$path'),
            headers: {
              'Content-Type': 'application/json',
              'X-Kami-Code': code,
              'X-Kami-App': appId,
              'X-Kami-Device': dev,
            },
            body: jsonEncode({'code': code, 'app': appId, 'device': dev}),
          )
          .timeout(const Duration(seconds: 15));
      return jsonDecode(utf8.decode(res.bodyBytes)) as Map;
    } catch (e) {
      return {'ok': false, 'key': 'net', 'message': '网络错误，请重试'};
    }
  }

  /// 首次激活（开始计时）
  static Future<Map> verify(String code) async {
    final r = await _post('/api/app/verify', code.trim().toUpperCase());
    if (r['ok'] == true) await _saveCode(code);
    return r;
  }

  /// 每次启动复核（不重复计时）
  static Future<Map> check(String code) => _post('/api/app/check', code);

  static Timer? _guard;

  /// 启动闸门：返回 null 表示通过，返回字符串表示需要提示用户并显示输入页
  static Future<String?> gate({void Function()? onLock}) async {
    final code = await savedCode();
    if (code == null) return '需要输入卡密';
    final r = await check(code);
    if (r['ok'] != true) {
      await clearCode();
      return (r['message'] ?? '卡密已失效').toString();
    }
    startGuard(onLock);
    return null;
  }

  /// 每 5 分钟复核；失效立即清卡密并回调 onLock
  static void startGuard(void Function()? onLock,
      {Duration interval = const Duration(minutes: 5)}) {
    _guard?.cancel();
    _guard = Timer.periodic(interval, (_) async {
      final code = await savedCode();
      if (code == null) return;
      final r = await check(code);
      if (r['ok'] != true) {
        await clearCode();
        _guard?.cancel();
        onLock?.call();
      }
    });
  }

  static void stopGuard() => _guard?.cancel();
}
"""

    # ================= React Native =================
    rn = """// ============================================================
//  React Native 接入 — 完整可用代码
// ============================================================
// 【第 1 步】安装依赖：
//     npm i @react-native-async-storage/async-storage
//
// 【第 2 步】复制下面整个 kami.js
// 【第 3 步】App 里：
//     import * as Kami from './kami';
//     const msg = await Kami.gate(() => setLocked(true));
//     if (msg) showKeyInput(msg);
// ============================================================

import AsyncStorage from '@react-native-async-storage/async-storage';

// ↓↓↓ 只改这两行 ↓↓↓
const BASE = '%(base)s';
const APP_ID = '%(app_id)s';
// ↑↑↑ 只改这两行 ↑↑↑

const KEY = 'kami_code';
const KEY_DEV = 'kami_device';

/** 设备唯一标识：首次生成后存本地，重启不丢 */
let _device = null;
async function deviceId() {
  if (_device) return _device;
  let v = await AsyncStorage.getItem(KEY_DEV);
  if (!v) {
    v = 'rn-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    await AsyncStorage.setItem(KEY_DEV, v);
  }
  _device = v;
  return v;
}

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
    const dev = await deviceId();
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 15000);
    const res = await fetch(BASE + path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Kami-Code': code,
        'X-Kami-App': APP_ID,
        'X-Kami-Device': dev,
      },
      body: JSON.stringify({ code, app: APP_ID, device: dev }),
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
  const r = await post('/api/app/verify', String(code).trim().toUpperCase());
  if (r.ok) await saveCode(code);
  return r;
}

/** 每次启动复核 */
export async function check(code) {
  return post('/api/app/check', code);
}

let _timer = null;

/** 每 5 分钟复核，失效清卡密并回调 */
export function startGuard(onLock, intervalMs = 5 * 60 * 1000) {
  stopGuard();
  _timer = setInterval(async () => {
    const code = await savedCode();
    if (!code) return;
    const r = await check(code);
    if (!r.ok) {
      await clearCode();
      stopGuard();
      onLock && onLock(r.message);
    }
  }, intervalMs);
}

export function stopGuard() {
  if (_timer) { clearInterval(_timer); _timer = null; }
}

/** 启动闸门：null=通过，字符串=需要显示输入页（内容为提示文字） */
export async function gate(onLock) {
  const code = await savedCode();
  if (!code) return '需要输入卡密';
  const r = await check(code);
  if (!r.ok) {
    await clearCode();
    return r.message || '卡密已失效';
  }
  startGuard(onLock);
  return null;
}
"""

    # ================= iOS Swift =================
    ios = """// ============================================================
//  iOS 接入（Swift）— 完整可用代码
// ============================================================
// 【第 1 步】复制下面整个 Kami.swift 到工程
// 【第 2 步】若接口是 http（非 https），Info.plist 需允许明文：
//     App Transport Security Settings → Allow Arbitrary Loads = YES
//     （正式环境请务必用 https）
// 【第 3 步】启动时：
//     Kami.gate(onPass: { exp in showMain() },
//               onNeedInput: { msg in showKeyInput(msg) })
// ============================================================

import Foundation
import UIKit

final class Kami {

    // ↓↓↓ 只改这两行 ↓↓↓
    static let base = "%(base)s"
    static let appId = "%(app_id)s"
    // ↑↑↑ 只改这两行 ↑↑↑

    private static let keyCode = "kami_code"
    private static let keyDev = "kami_device"

    // MARK: - 卡密存取

    static var savedCode: String? {
        let v = UserDefaults.standard.string(forKey: keyCode)
        return (v?.isEmpty ?? true) ? nil : v
    }

    static func save(_ code: String) {
        UserDefaults.standard.set(code.trimmingCharacters(in: .whitespaces).uppercased(),
                                  forKey: keyCode)
    }

    static func clear() { UserDefaults.standard.removeObject(forKey: keyCode) }

    // MARK: - 设备号（重启/重装都保留）

    static var deviceId: String {
        if let v = UserDefaults.standard.string(forKey: keyDev), !v.isEmpty { return v }
        let v = UIDevice.current.identifierForVendor?.uuidString ?? UUID().uuidString
        UserDefaults.standard.set(v, forKey: keyDev)
        return v
    }

    // MARK: - 请求

    struct Result {
        let ok: Bool
        let key: String
        let message: String
        let expireText: String
    }

    private static func post(_ path: String, _ code: String,
                             _ completion: @escaping (Result) -> Void) {
        guard let url = URL(string: base + path) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 15
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(code, forHTTPHeaderField: "X-Kami-Code")
        req.setValue(appId, forHTTPHeaderField: "X-Kami-App")
        req.setValue(deviceId, forHTTPHeaderField: "X-Kami-Device")
        req.httpBody = try? JSONSerialization.data(
            withJSONObject: ["code": code, "app": appId, "device": deviceId])

        URLSession.shared.dataTask(with: req) { data, _, _ in
            guard let data,
                  let j = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                DispatchQueue.main.async {
                    completion(Result(ok: false, key: "net",
                                      message: "网络错误，请重试", expireText: ""))
                }
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

    /// 首次激活（开始计时）
    static func verify(_ code: String, _ completion: @escaping (Result) -> Void) {
        post("/api/app/verify", code.trimmingCharacters(in: .whitespaces).uppercased()) { r in
            if r.ok { save(code) }
            completion(r)
        }
    }

    /// 每次启动复核（不重复计时）
    static func check(_ code: String, _ completion: @escaping (Result) -> Void) {
        post("/api/app/check", code, completion)
    }

    // MARK: - 启动闸门 + 定时复核

    private static var timer: Timer?

    /// 每 5 分钟复核，失效清卡密并回调
    static func startGuard(onLock: @escaping () -> Void) {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 5 * 60, repeats: true) { _ in
            guard let code = savedCode else { timer?.invalidate(); return }
            check(code) { r in
                if !r.ok {
                    clear()
                    timer?.invalidate()
                    onLock()
                }
            }
        }
    }

    /// 启动闸门
    static func gate(onPass: @escaping (String) -> Void,
                     onNeedInput: @escaping (String) -> Void) {
        guard let code = savedCode else { onNeedInput("需要输入卡密"); return }
        check(code) { r in
            if r.ok {
                onPass(r.expireText)
                startGuard { onNeedInput("卡密已失效") }
            } else {
                clear()
                onNeedInput(r.message)
            }
        }
    }
}
"""

    # ================= 网页 / WebView =================
    webview = """// ============================================================
//  网页 / WebView 套壳 / 静态网站（最简单，1 行搞定）
// ============================================================
// 把下面这一行放进你的网页 <head> 或 <body> 里，弹窗会自动出现：
//
// <script src="%(base)s/embed.js?site=%(app_id)s"></script>
//
// 自带能力（无需额外代码）：
//   · 21 种语言自动切换（跟随访客浏览器语言）
//   · 解锁方式：模糊 / 变暗 / 完全隐藏
//   · 5 分钟自动复核，卡密失效立即重新上锁
//   · 设备绑定：同一卡密换电脑会被拒绝
// ============================================================

// ————————————————————————————————————————————————
// 本地 HTML 打包进 App（离线套壳）也能用，只要用户能联网。
// 想自己控制界面、不用自带弹窗，就按下面自己调接口：
// ————————————————————————————————————————————————

const BASE = '%(base)s';
const APP_ID = '%(app_id)s';

/** 设备唯一标识：存 localStorage + 浏览器指纹，清缓存也认得出 */
function kamiDevice() {
  var k = 'kami_device_id';
  var v = localStorage.getItem(k);
  var fp = [screen.width + 'x' + screen.height, screen.colorDepth,
            new Date().getTimezoneOffset(), navigator.language,
            navigator.hardwareConcurrency, navigator.platform].join('|');
  if (!v) {
    v = 'wv-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
    localStorage.setItem(k, v);
  }
  return v + '#' + fp;
}

async function kamiVerify(code) {
  const res = await fetch(BASE + '/api/app/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Kami-Code': code,
               'X-Kami-App': APP_ID, 'X-Kami-Device': kamiDevice() },
    body: JSON.stringify({ code, app: APP_ID, device: kamiDevice() })
  });
  return res.json();   // { ok, key, message, expire_at, expire_text, days_left }
}

async function kamiCheck(code) {
  const res = await fetch(BASE + '/api/app/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Kami-Code': code,
               'X-Kami-App': APP_ID, 'X-Kami-Device': kamiDevice() },
    body: JSON.stringify({ code, app: APP_ID, device: kamiDevice() })
  });
  return res.json();
}

// ——— 页面上的两个区域：内容区 + 卡密输入层 ———
// <div id="app-content">你的正文</div>
// <div id="kami-mask" style="display:none;position:fixed;inset:0;background:#111;
//      color:#fff;z-index:9999;align-items:center;justify-content:center">
//   <div style="text-align:center">
//     <p id="kami-msg">请输入卡密</p>
//     <input id="kami-input" placeholder="XXXX-XXXX-XXXX-XXXX">
//     <button id="kami-btn">验证</button>
//   </div>
// </div>
const content = document.getElementById('app-content');
const mask    = document.getElementById('kami-mask');
const msgEl   = document.getElementById('kami-msg');
const inputEl = document.getElementById('kami-input');
const btnEl   = document.getElementById('kami-btn');

function showContent(text) {
  if (mask) mask.style.display = 'none';
  if (content) content.style.filter = '';
  console.log('已解锁，到期：' + (text || ''));
}

function showInput(msg) {
  if (mask) { mask.style.display = 'flex'; }
  if (content) content.style.filter = 'blur(8px)';
  if (msgEl && msg) msgEl.textContent = msg;
  if (inputEl) inputEl.value = '';
  if (inputEl) inputEl.focus();
}

// 点「验证」按钮 → 首次激活
if (btnEl) {
  btnEl.onclick = async function () {
    const code = (inputEl.value || '').trim().toUpperCase();
    if (!code) { msgEl.textContent = '请输入卡密'; return; }
    btnEl.disabled = true;
    msgEl.textContent = '验证中…';
    try {
      const r = await kamiVerify(code);
      if (r.ok) {
        localStorage.setItem('kami_code', code);
        showContent(r.expire_text);
      } else {
        msgEl.textContent = r.message || '验证失败';
      }
    } catch (e) {
      msgEl.textContent = '网络错误，请检查网络后重试';
    }
    btnEl.disabled = false;
  };
}

// ——— 启动逻辑：有存档就复核，没有就弹输入 ———
(async function startup() {
  const saved = localStorage.getItem('kami_code');
  if (!saved) { showInput('请输入卡密'); return; }
  const r = await kamiCheck(saved);
  if (r.ok) { showContent(r.expire_text); }
  else { localStorage.removeItem('kami_code'); showInput(r.message); }
})();

// ——— 每 5 分钟自动复核 ———
setInterval(async function () {
  const code = localStorage.getItem('kami_code');
  if (!code) return;
  const r = await kamiCheck(code);
  if (!r.ok) { localStorage.removeItem('kami_code'); showInput(r.message); }
}, 5 * 60 * 1000);
"""

    # ================= Windows C# =================
    csharp = """// ============================================================
//  Windows 桌面（C# WinForms / WPF）— 完整可用代码
// ============================================================
// 【第 1 步】复制下面整个 KamiGate.cs 到项目（命名空间按需改）
// 【第 2 步】主窗体 Load 事件：
//     var r = await KamiGate.GateAsync();
//     if (!r.ok) { ShowKeyInput(r.message); }   // 弹输入框
// 【第 3 步】用户输完卡密：
//     var v = await KamiGate.VerifyAsync(txtCode.Text);
//     if (v.ok) { ShowMain(v.expire_text); }
//     else { MessageBox.Show(v.message); }
// 【第 4 步】验证通过后启动复核：
//     KamiGate.StartGuard(msg => { MessageBox.Show(msg); Application.Exit(); });
// ============================================================

using System;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace YourApp
{
    public static class KamiGate
    {
        // ↓↓↓ 只改这两行 ↓↓↓
        private const string Base = "%(base)s";
        private const string AppId = "%(app_id)s";
        // ↑↑↑ 只改这两行 ↑↑↑

        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(15)
        };

        public class Result
        {
            public bool ok { get; set; }
            public string key { get; set; } = "";
            public string message { get; set; } = "";
            public string expire_text { get; set; } = "";
            public int? days_left { get; set; }
        }

        // ---------- 卡密存取（记住用户输入） ----------
        private static string CodePath =>
            System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "YourApp", "kami_code.txt");

        public static string SavedCode()
        {
            try
            {
                if (!System.IO.File.Exists(CodePath)) return null;
                var v = System.IO.File.ReadAllText(CodePath).Trim();
                return v.Length == 0 ? null : v;
            }
            catch { return null; }
        }

        private static void SaveCode(string code)
        {
            try
            {
                System.IO.Directory.CreateDirectory(
                    System.IO.Path.GetDirectoryName(CodePath));
                System.IO.File.WriteAllText(CodePath, code.Trim().ToUpper());
            }
            catch { }
        }

        private static void ClearCode()
        {
            try { System.IO.File.Delete(CodePath); } catch { }
        }

        // ---------- 设备号（注册表持久化，重启不丢） ----------
        private static string _device;

        public static string DeviceId
        {
            get
            {
                if (_device != null) return _device;
                try
                {
                    using var key = Microsoft.Win32.Registry.CurrentUser
                        .CreateSubKey(@"Software\\\\KamiGate");
                    var v = key?.GetValue("device_id") as string;
                    if (!string.IsNullOrEmpty(v)) { _device = v; return v; }
                    v = Environment.MachineName + "-" + Guid.NewGuid().ToString("N");
                    key?.SetValue("device_id", v);
                    _device = v;
                    return v;
                }
                catch
                {
                    _device = Environment.MachineName;
                    return _device;
                }
            }
        }

        // ---------- 请求 ----------
        private static async Task<Result> PostAsync(string path, string code)
        {
            try
            {
                var req = new HttpRequestMessage(HttpMethod.Post, Base + path);
                req.Headers.Add("X-Kami-Code", code);
                req.Headers.Add("X-Kami-App", AppId);
                req.Headers.Add("X-Kami-Device", DeviceId);
                req.Content = new StringContent(
                    JsonSerializer.Serialize(new { code, app = AppId, device = DeviceId }),
                    Encoding.UTF8, "application/json");

                var resp = await Http.SendAsync(req);
                var json = await resp.Content.ReadAsStringAsync();
                return JsonSerializer.Deserialize<Result>(json,
                    new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
                    ?? new Result { ok = false, message = "返回数据异常" };
            }
            catch
            {
                return new Result { ok = false, key = "net", message = "网络错误，请检查网络后重试" };
            }
        }

        /// <summary>首次激活（开始计时）</summary>
        public static async Task<Result> VerifyAsync(string code)
        {
            var r = await PostAsync("/api/app/verify", code.Trim().ToUpper());
            if (r.ok) SaveCode(code);
            return r;
        }

        /// <summary>每次启动复核（不重复计时）</summary>
        public static Task<Result> CheckAsync(string code) => PostAsync("/api/app/check", code);

        /// <summary>启动闸门：有卡密则复核并返回结果</summary>
        public static async Task<Result> GateAsync()
        {
            var code = SavedCode();
            if (code == null)
                return new Result { ok = false, key = "notyet", message = "需要输入卡密" };
            var r = await CheckAsync(code);
            if (!r.ok) ClearCode();
            return r;
        }

        /// <summary>每 5 分钟复核，失效回调（在后台线程，记得切回 UI 线程）</summary>
        public static async void StartGuard(Action<string> onLock)
        {
            while (true)
            {
                await Task.Delay(TimeSpan.FromMinutes(5));
                var code = SavedCode();
                if (code == null) return;
                var r = await CheckAsync(code);
                if (!r.ok)
                {
                    ClearCode();
                    onLock(r.message);
                    return;
                }
            }
        }
    }
}
"""

    # ================= Python =================
    python = """# ============================================================
#  Python 桌面 / 脚本（tkinter、PyQt、命令行通用）— 完整可用代码
# ============================================================
# 【第 1 步】安装依赖：
#     pip install requests
#
# 【第 2 步】复制下面整个 kami.py
# 【第 3 步】程序入口：
#     from kami import gate, verify, start_guard
#
#     if not gate(lambda msg: print("锁定:", msg)):
#         code = input("请输入卡密：")
#         r = verify(code)
#         print(r.get("message"))
#         if not r.get("ok"):
#             raise SystemExit(1)
#     start_guard(lambda msg: print("卡密失效:", msg))
# ============================================================

import hashlib
import os
import platform
import threading
import time
import uuid

import requests

# ↓↓↓ 只改这两行 ↓↓↓
BASE = "%(base)s"
APP_ID = "%(app_id)s"
# ↑↑↑ 只改这两行 ↑↑↑

TIMEOUT = 15
_CODE_FILE = os.path.join(os.path.expanduser("~"), ".kami_code")
_DEV_FILE = os.path.join(os.path.expanduser("~"), ".kami_device_id")


def device_id() -> str:
    \"\"\"设备唯一标识：存文件，重启不丢（只允许 ASCII，中文电脑名会自动转码）\"\"\"
    def _mk() -> str:
        raw = "{}-{}".format(platform.node() or "pc", uuid.getnode())
        # HTTP 头只支持 ASCII，中文电脑名要转一下
        try:
            raw.encode("ascii")
            return raw
        except UnicodeEncodeError:
            return "h-" + hashlib.md5(raw.encode("utf-8")).hexdigest()
    def _ascii(x: str) -> str:
        # 已有文件里也可能是中文，统一兜底转码
        try:
            x.encode("ascii")
            return x
        except UnicodeEncodeError:
            return "h-" + hashlib.md5(x.encode("utf-8")).hexdigest()
    try:
        if os.path.exists(_DEV_FILE):
            v = open(_DEV_FILE, encoding="utf-8").read().strip()
            if v:
                return _ascii(v)
        v = _mk()
        with open(_DEV_FILE, "w", encoding="utf-8") as f:
            f.write(v)
        return v
    except Exception:
        return _mk()


def _post(path: str, code: str) -> dict:
    dev = device_id()
    try:
        r = requests.post(
            BASE + path,
            json={"code": code, "app": APP_ID, "device": dev},
            headers={"X-Kami-Code": code, "X-Kami-App": APP_ID, "X-Kami-Device": dev},
            timeout=TIMEOUT,
        )
        return r.json()
    except Exception:
        return {"ok": False, "key": "net", "message": "网络错误，请重试"}


def verify(code: str) -> dict:
    \"\"\"首次激活（开始计时）\"\"\"
    res = _post("/api/app/verify", code.strip().upper())
    if res.get("ok"):
        _save(code)
    return res


def check(code: str) -> dict:
    \"\"\"每次启动校验（不激活、不扣时长）\"\"\"
    return _post("/api/app/check", code)


def _save(code: str) -> None:
    try:
        with open(_CODE_FILE, "w", encoding="utf-8") as f:
            f.write(code.strip().upper())
    except Exception:
        pass


def _load():
    try:
        if not os.path.exists(_CODE_FILE):
            return None
        v = open(_CODE_FILE, encoding="utf-8").read().strip()
        return v or None
    except Exception:
        return None


def _clear() -> None:
    try:
        os.remove(_CODE_FILE)
    except Exception:
        pass


def gate(on_lock=None) -> bool:
    \"\"\"启动闸门：True=通过（并已启动定时复核），False=需要输入卡密\"\"\"
    code = _load()
    if not code:
        return False
    r = check(code)
    if not r.get("ok"):
        _clear()
        return False
    start_guard(on_lock or (lambda m: None))
    return True


def start_guard(on_lock=None, interval: int = 300) -> None:
    \"\"\"每 5 分钟复核；失效清卡密并回调 on_lock(提示文字)\"\"\"
    def loop():
        while True:
            time.sleep(interval)
            code = _load()
            if not code:
                return
            r = check(code)
            if not r.get("ok"):
                _clear()
                if on_lock:
                    on_lock(r.get("message", "卡密已失效"))
                return
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    if not gate(lambda m: print("卡密失效：", m)):
        user_code = input("请输入卡密：").strip()
        res = verify(user_code)
        print(res.get("message"), res.get("expire_text", ""))
        if not res.get("ok"):
            raise SystemExit(1)
    print("已解锁，继续运行主程序...")
"""

    # ================= 其他软件 =================
    other = """# ============================================================
#  其他软件 / 通用接入（任意能发 HTTP 的软件都能用）
# ============================================================
# 适用：AutoHotkey、按键精灵、易语言、Delphi、VB6、Go、PHP、
#       Electron、游戏插件、脚本工具、Lua、C++、Java 桌面……
# ============================================================

# ── 接口一：首次激活（校验并开始计时）──────────────────────
#   POST %(base)s/api/app/verify
#   Header: X-Kami-App: %(app_id)s
#   Header: X-Kami-Code: 用户输入的卡密
#   Header: X-Kami-Device: 本机唯一标识
#
# ── 接口二：每次启动复核（不重复计时）──────────────────────
#   POST %(base)s/api/app/check
#   Header 同上
#
# ── 返回 JSON ─────────────────────────────────────────────
#   {"ok": true,  "key": "ok",     "message": "验证成功", "expire_text": "永久有效"}
#   {"ok": false, "key": "invalid","message": "卡密无效"}
#   {"ok": false, "key": "expired","message": "卡密已过期"}
#   {"ok": false, "key": "device", "message": "此卡密已在其他设备使用…"}
#   {"ok": false, "key": "limit",  "message": "该卡密仅限 xxx 使用"}
#   {"ok": false, "key": "rate",   "message": "操作过于频繁"}
#   {"ok": false, "key": "net",    "message": "网络错误"}
#
#   → 判定通过只看 ok 是否为 true

# ── 方式一：Windows 命令行（bat / AHK / 易语言直接调）──────
curl -s -X POST "%(base)s/api/app/verify" ^
     -H "X-Kami-App: %(app_id)s" ^
     -H "X-Kami-Code: 卡密" ^
     -H "X-Kami-Device: %%COMPUTERNAME%%"
#
# 返回里出现 "ok":true 就是通过。
# 机器码用 %%COMPUTERNAME%%（电脑名），或用硬件 UUID：
#   wmic csproduct get uuid
#
# AHK 示例：
#   oHttp := ComObjCreate("WinHttp.WinHttpRequest.5.1")
#   oHttp.Open("POST", "%(base)s/api/app/verify", false)
#   oHttp.SetRequestHeader("X-Kami-App", "%(app_id)s")
#   oHttp.SetRequestHeader("X-Kami-Code", code)
#   oHttp.SetRequestHeader("X-Kami-Device", A_ComputerName)
#   oHttp.Send()
#   if InStr(oHttp.ResponseText, "\"ok\":true") { ...通过... }

# ── 方式二：Go 参考实现（可编译成 exe）─────────────────────
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
    "os"
    "os/exec"
    "strings"
    "time"
)

const baseURL = "%(base)s"
const appID = "%(app_id)s"
const codeFile = ".kami_code"

func call(path, code, device string) map[string]interface{} {
    req, _ := http.NewRequest("POST", baseURL+path, bytes.NewBufferString(""))
    req.Header.Set("X-Kami-App", appID)
    req.Header.Set("X-Kami-Code", code)
    req.Header.Set("X-Kami-Device", device)
    c := &http.Client{Timeout: 15 * time.Second}
    resp, err := c.Do(req)
    if err != nil {
        return map[string]interface{}{"ok": false, "message": "网络错误"}
    }
    defer resp.Body.Close()
    var out map[string]interface{}
    json.NewDecoder(resp.Body).Decode(&out)
    return out
}

// 判定是否通过：只看 ok 字段是不是 true
func passed(r map[string]interface{}) bool {
    b, _ := r["ok"].(bool)
    return b
}

// 取提示文字
func msg(r map[string]interface{}) string {
    s, _ := r["message"].(string)
    return s
}


// 设备号：优先主板 UUID，取不到用电脑名
func deviceID() string {
    out, err := exec.Command("wmic", "csproduct", "get", "uuid").Output()
    if err == nil {
        f := strings.Fields(string(out))
        if len(f) > 1 && f[1] != "" {
            return f[1]
        }
    }
    host, _ := os.Hostname()
    return host
}

func main() {
    dev := deviceID()
    raw, _ := os.ReadFile(codeFile)
    code := strings.TrimSpace(string(raw))

    if code == "" {
        fmt.Print("请输入卡密：")
        fmt.Scanln(&code)
        r := call("/api/app/verify", strings.ToUpper(code), dev)
        if !passed(r) {
            fmt.Println("卡密无效：", msg(r))
            os.Exit(1)
        }
        os.WriteFile(codeFile, []byte(strings.ToUpper(code)), 0600)
        fmt.Println("验证成功，到期：", r["expire_text"])
    } else {
        r := call("/api/app/check", code, dev)
        if !passed(r) {
            os.Remove(codeFile)
            fmt.Println("卡密已失效，请重新输入：", msg(r))
            os.Exit(1)
        }
        fmt.Println("已解锁，到期：", r["expire_text"])
    }

    // 每 5 分钟后台复核
    go func() {
        for {
            time.Sleep(5 * time.Minute)
            r := call("/api/app/check", code, dev)
            if !passed(r) {
                os.Remove(codeFile)
                fmt.Println("卡密已失效，程序退出")
                os.Exit(2)
            }
        }
    }()

    // ↓↓↓ 这里放你自己的业务逻辑 ↓↓↓
    fmt.Println("程序已运行…")
    select {}
}
"""

    head = _head(base, app_id)
    faq = COMMON_FAQ

    def fill(tpl: str) -> str:
        # 用 replace 而不是 % 格式化：代码里百分号太多，% 格式化会出错
        return tpl.replace("%(base)s", base).replace("%(app_id)s", app_id)

    return {
        "Android · Kotlin": head + fill(kotlin) + faq,
        "Android · Java": head + fill(java) + faq,
        "Flutter": head + fill(flutter) + faq,
        "React Native": head + fill(rn) + faq,
        "iOS · Swift": head + fill(ios) + faq,
        "网页 / WebView 套壳": head + fill(webview) + faq,
        "Windows · C#": head + fill(csharp) + faq,
        "Python 桌面": head + fill(python) + faq,
        "其他软件 · 通用 HTTP": head + fill(other) + faq,
    }
