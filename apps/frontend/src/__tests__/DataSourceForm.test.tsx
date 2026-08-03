import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { DataSourceDetail } from "@chatbi/shared";
import { DataSourceForm } from "../components/DataSourceForm";
import { ApiError, createDataSource, testDsConfig, updateDataSource } from "../api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, testDsConfig: vi.fn(), createDataSource: vi.fn(), updateDataSource: vi.fn() };
});

const detail: DataSourceDetail = {
  id: "ds1", name: "销售库", kind: "mysql", target: "mysql://bi_ro@10.0.0.5:3306/sales",
  status: "ok", writePrivilege: "readonly", lastCheckAt: null, lastCheckError: null,
  schemaFetchedAt: null, tableCount: 12, hasPassword: true,
  connection: { host: "10.0.0.5", port: 3306, database: "sales", user: "bi_ro", ssl: false },
};

const onSaved = vi.fn();
const onCancel = vi.fn();
const mount = (initial?: DataSourceDetail) =>
  render(<DataSourceForm initial={initial} onSaved={onSaved} onCancel={onCancel} />);

const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const click = (name: RegExp | string) => fireEvent.click(screen.getByRole("button", { name }));

/** 新建一个 MySQL 源要填的最少字段。 */
const fillMysql = () => {
  fill("名称", "销售库");
  fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "mysql" } });
  fill("主机", "10.0.0.5");
  fill("数据库", "sales");
  fill("用户名", "bi_ro");
  fill("密码", "s3cret");
};

beforeEach(() => {
  onSaved.mockReset();
  onCancel.mockReset();
  vi.mocked(testDsConfig).mockReset();
  vi.mocked(createDataSource).mockReset();
  vi.mocked(updateDataSource).mockReset();
});

describe("表单字段随 kind 变化", () => {
  it("sqlite 只要文件路径", () => {
    mount();
    expect(screen.getByLabelText("文件路径")).toBeTruthy();
    expect(screen.queryByLabelText("主机")).toBeNull();
  });

  it("换成 mysql 出现主机/端口/库/用户/密码/SSL,没有 schema", () => {
    mount();
    fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "mysql" } });
    for (const l of ["主机", "端口", "数据库", "用户名", "密码"]) {
      expect(screen.getByLabelText(l)).toBeTruthy();
    }
    expect(screen.getByLabelText("启用 SSL")).toBeTruthy();
    expect(screen.queryByLabelText("schema")).toBeNull();
    expect(screen.queryByLabelText("文件路径")).toBeNull();
  });

  it("postgres 多一个 schema 字段", () => {
    mount();
    fireEvent.change(screen.getByLabelText("数据库类型"), { target: { value: "postgres" } });
    expect(screen.getByLabelText("schema")).toBeTruthy();
  });

  it("端口留空按 kind 用默认值", async () => {
    vi.mocked(createDataSource).mockResolvedValue(detail);
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(vi.mocked(createDataSource)).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[0][1]).toMatchObject({ kind: "mysql", port: 3306 });
  });
});

describe("表单测连", () => {
  it("测连成功显示表数量与权限", async () => {
    vi.mocked(testDsConfig).mockResolvedValue({ ok: true, writePrivilege: "writable", tableCount: 9 });
    mount();
    fillMysql();
    click("测试连接");
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("9 张表"));
    expect(screen.getByRole("status").textContent).toContain("可写");
    expect(vi.mocked(testDsConfig).mock.calls[0][0]).toMatchObject({
      kind: "mysql", host: "10.0.0.5", database: "sales", user: "bi_ro", password: "s3cret", ssl: false,
    });
  });

  it("测连失败显示可读消息,原文折在详情里", async () => {
    vi.mocked(testDsConfig).mockRejectedValue(
      new ApiError("AUTH_ERROR", "认证失败,请检查用户名与密码", "ER_ACCESS_DENIED_ERROR"),
    );
    mount();
    fillMysql();
    click("测试连接");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("认证失败"));
    fireEvent.click(screen.getByText("查看详情"));
    expect(screen.getByText(/ER_ACCESS_DENIED_ERROR/)).toBeTruthy();
  });
});

describe("新建", () => {
  it("名称为空时不发请求,就地提示", () => {
    mount();
    click("保存");
    expect(vi.mocked(createDataSource)).not.toHaveBeenCalled();
    expect(screen.getByTestId("name-error").textContent).toContain("请填写数据源名称");
  });

  it("保存成功回调 onSaved", async () => {
    vi.mocked(createDataSource).mockResolvedValue(detail);
    mount();
    fill("名称", "示例库");
    fill("文件路径", "./data/chatbi.db");
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[0][0]).toBe("示例库");
    expect(vi.mocked(createDataSource).mock.calls[0][1]).toEqual({ kind: "sqlite", path: "./data/chatbi.db" });
    expect(vi.mocked(createDataSource).mock.calls[0][2]).toBeUndefined();
  });

  it("测连失败但 canForce 时给「仍然保存」,点它带 force 重发", async () => {
    vi.mocked(createDataSource)
      .mockRejectedValueOnce(new ApiError("CONNECTION_ERROR", "无法连接到 10.0.0.5:3306", "ECONNREFUSED", true))
      .mockResolvedValueOnce(detail);
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(screen.getByRole("button", { name: "仍然保存" })).toBeTruthy());
    click("仍然保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(createDataSource).mock.calls[1][2]).toBe(true);
  });

  it("canForce 不为真时不给「仍然保存」", async () => {
    vi.mocked(createDataSource).mockRejectedValue(new ApiError("DB_NOT_FOUND", "数据库 sales 不存在"));
    mount();
    fillMysql();
    click("保存");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("不存在"));
    expect(screen.queryByRole("button", { name: "仍然保存" })).toBeNull();
  });

  it("重名错误落到名称字段旁", async () => {
    vi.mocked(createDataSource).mockRejectedValue(new ApiError("DUPLICATE_NAME", "已有同名数据源"));
    mount();
    fill("名称", "销售库");
    fill("文件路径", "./x.db");
    click("保存");
    await waitFor(() => expect(screen.getByTestId("name-error").textContent).toContain("已有同名数据源"));
  });
});

describe("编辑", () => {
  it("回填已有连接字段,并说明密码留空表示不改", () => {
    mount(detail);
    expect((screen.getByLabelText("名称") as HTMLInputElement).value).toBe("销售库");
    expect((screen.getByLabelText("主机") as HTMLInputElement).value).toBe("10.0.0.5");
    expect((screen.getByLabelText("端口") as HTMLInputElement).value).toBe("3306");
    expect((screen.getByLabelText("用户名") as HTMLInputElement).value).toBe("bi_ro");
    expect((screen.getByLabelText("密码") as HTMLInputElement).value).toBe("");
    expect(screen.getByTestId("password-hint").textContent).toContain("留空表示不修改");
  });

  it("密码留空时请求体里不带 password", async () => {
    vi.mocked(updateDataSource).mockResolvedValue(detail);
    mount(detail);
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const input = vi.mocked(updateDataSource).mock.calls[0][2] as Record<string, unknown>;
    expect("password" in input).toBe(false);
    expect(vi.mocked(updateDataSource).mock.calls[0][0]).toBe("ds1");
  });

  it("填了新密码就带上", async () => {
    vi.mocked(updateDataSource).mockResolvedValue(detail);
    mount(detail);
    fill("密码", "newpass");
    click("保存");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(updateDataSource).mock.calls[0][2]).toMatchObject({ password: "newpass" });
  });

  it("取消回调 onCancel", () => {
    mount(detail);
    click("取消");
    expect(onCancel).toHaveBeenCalled();
  });
});
