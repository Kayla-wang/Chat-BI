import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, rmSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { encryptJson, decryptJson, loadKey, DecryptError } from "../src/appDb/secrets";

const tmpDir = join(process.cwd(), ".tmp-test-secrets");
const keyPath = join(tmpDir, "app.key");
const key = randomBytes(32);

beforeEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  mkdirSync(tmpDir, { recursive: true });
  delete process.env.APP_KEY;
});
afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
  delete process.env.APP_KEY;
});

const secret = { host: "10.0.0.5", port: 3306, user: "bi_ro", password: "p@ss w0rd 中文" };

describe("加解密往返", () => {
  it("解出来和存进去的一模一样", () => {
    expect(decryptJson(encryptJson(secret, key), key)).toEqual(secret);
  });

  it("密文里不含明文密码", () => {
    const { cipher } = encryptJson(secret, key);
    expect(cipher.toString("utf8")).not.toContain("p@ss");
    expect(cipher.toString("latin1")).not.toContain("p@ss");
  });

  it("同一明文两次加密的密文不同(IV 随机)", () => {
    const a = encryptJson(secret, key);
    const b = encryptJson(secret, key);
    expect(a.iv.equals(b.iv)).toBe(false);
    expect(a.cipher.equals(b.cipher)).toBe(false);
  });
});

describe("完整性校验", () => {
  const flip = (b: Buffer): Buffer => {
    const c = Buffer.from(b);
    c[0] = c[0] ^ 0xff;
    return c;
  };

  it("篡改密文则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, cipher: flip(s.cipher) }, key)).toThrow(DecryptError);
  });
  it("篡改 IV 则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, iv: flip(s.iv) }, key)).toThrow(DecryptError);
  });
  it("篡改认证标签则解密失败", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson({ ...s, tag: flip(s.tag) }, key)).toThrow(DecryptError);
  });
  it("换一把钥匙解不开", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson(s, randomBytes(32))).toThrow(DecryptError);
  });
  it("错误消息是可读中文,不泄露密文", () => {
    const s = encryptJson(secret, key);
    expect(() => decryptJson(s, randomBytes(32))).toThrow(/凭据无法解密/);
  });
});

describe("loadKey", () => {
  it("APP_KEY 优先,不落文件", () => {
    const raw = randomBytes(32);
    process.env.APP_KEY = raw.toString("base64");
    expect(loadKey(keyPath).equals(raw)).toBe(true);
    expect(existsSync(keyPath)).toBe(false);
  });

  it("APP_KEY 长度不对时报可读错误", () => {
    process.env.APP_KEY = Buffer.from("太短").toString("base64");
    expect(() => loadKey(keyPath)).toThrow(/APP_KEY 必须是 32 字节/);
  });

  it("没有 APP_KEY 时生成密钥文件", () => {
    const k = loadKey(keyPath);
    expect(k).toHaveLength(32);
    expect(readFileSync(keyPath)).toHaveLength(32);
  });

  it("第二次调用复用同一个密钥文件", () => {
    expect(loadKey(keyPath).equals(loadKey(keyPath))).toBe(true);
  });

  it("密钥文件长度不对时报可读错误,不静默重建", () => {
    loadKey(keyPath);
    rmSync(keyPath);
    mkdirSync(tmpDir, { recursive: true });
    writeFileSync(keyPath, randomBytes(7));
    expect(() => loadKey(keyPath)).toThrow(/密钥文件.*32 字节/);
  });
});
