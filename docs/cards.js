// ===== 卡密配置（纯静态版）=====
// 修改规则：
//   code: 卡密（建议保持 XXXX-XXXX-XXXX 格式，字母用大写，避开 0/O/1/I）
//   days: 有效天数（0 = 永久，验证通过后按浏览器本地记录计时）
//   note: 备注（仅自用，不显示给用户）
// 注意：此文件对所有人可见（纯静态方案的特点），请勿放置高价值权益卡密。
window.KAMI_CARDS = [
  { code: "ZUJK-LMKN-5RE8-E5Q4", days: 30, note: "演示卡密1" },
  { code: "BYVB-7Z3J-CPDJ-7CW8", days: 0,  note: "演示卡密2（永久）" },
  { code: "AHSP-7TRG-7LFW-HYBW", days: 7,  note: "演示卡密3" }
];
