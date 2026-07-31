import type { Driver } from "../driver";
import type { DsConfig } from "../types";
import { createSqliteDriver } from "./sqlite";
import { createMysqlDriver } from "./mysql";
import { createPgDriver } from "./postgres";

export function createDriverFor(config: DsConfig): Driver {
  switch (config.kind) {
    case "sqlite": return createSqliteDriver(config);
    case "mysql": return createMysqlDriver(config);
    case "postgres": return createPgDriver(config);
  }
}
