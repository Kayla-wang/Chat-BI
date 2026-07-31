import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, chmodSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { config } from "../config";

const ALGO = "aes-256-gcm";
const IV_BYTES = 12;   // GCM 的标准 IV 长度
const KEY_BYTES = 32;  // AES-256

export interface Sealed { cipher: Buffer; iv: Buffer; tag: Buffer }

/** 解密或认证失败。上层据此映射成 DECRYPT_ERROR,不要用裸 Error。 */
export class DecryptError extends Error {
  constructor(message = "凭据无法解密,请重新填写连接信息") { super(message); this.name = "DecryptError"; }
}

export function encryptJson(value: unknown, key: Buffer): Sealed {
  const iv = randomBytes(IV_BYTES);
  const c = createCipheriv(ALGO, key, iv);
  const cipher = Buffer.concat([c.update(JSON.stringify(value), "utf8"), c.final()]);
  return { cipher, iv, tag: c.getAuthTag() };
}

export function decryptJson<T>(sealed: Sealed, key: Buffer): T {
  try {
    const d = createDecipheriv(ALGO, key, sealed.iv);
    d.setAuthTag(sealed.tag);
    const plain = Buffer.concat([d.update(sealed.cipher), d.final()]).toString("utf8");
    return JSON.parse(plain) as T;
  } catch {
    // 不把原始错误或密文带出去。
    throw new DecryptError();
  }
}

/**
 * 密钥来源:APP_KEY(32 字节 base64)优先,否则读/建密钥文件。
 * 长度不对一律报错,绝不静默重新生成——那会把「换了钥匙」伪装成「数据损坏」。
 */
export function loadKey(keyPath: string = config.appKeyPath): Buffer {
  const fromEnv = process.env.APP_KEY;
  if (fromEnv) {
    const k = Buffer.from(fromEnv, "base64");
    if (k.length !== KEY_BYTES) {
      throw new Error(`APP_KEY 必须是 32 字节的 base64,当前解出 ${k.length} 字节`);
    }
    return k;
  }
  if (existsSync(keyPath)) {
    const k = readFileSync(keyPath);
    if (k.length !== KEY_BYTES) {
      throw new Error(`密钥文件 ${keyPath} 应为 32 字节,实际 ${k.length} 字节;请恢复备份或删除后重新配置数据源`);
    }
    return k;
  }
  mkdirSync(dirname(keyPath), { recursive: true });
  const k = randomBytes(KEY_BYTES);
  writeFileSync(keyPath, k);
  // Windows 上 mode 位不由 NTFS ACL 采纳,这行等于无操作,不视为失败。
  try { chmodSync(keyPath, 0o600); } catch { /* 平台不支持,忽略 */ }
  return k;
}
