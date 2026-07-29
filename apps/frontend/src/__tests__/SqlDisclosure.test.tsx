import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SqlDisclosure } from "../components/SqlDisclosure";

const SQL = "SELECT region, SUM(total_amount) AS amount FROM orders GROUP BY region";

describe("SqlDisclosure", () => {
  it("summary 是「查看 SQL」", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByText("查看 SQL")).toBeTruthy();
  });
  it("默认收起", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByTestId("sql-disclosure").hasAttribute("open")).toBe(false);
  });
  it("SQL 原文在 DOM 里,可被核对", () => {
    render(<SqlDisclosure sql={SQL} />);
    expect(screen.getByText(/GROUP BY region/)).toBeTruthy();
  });
  it("空 SQL 时不渲染", () => {
    const { container } = render(<SqlDisclosure sql="" />);
    expect(container.firstChild).toBeNull();
  });
});
