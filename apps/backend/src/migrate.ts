import type { DbClient } from "./dbClient";

const DDL = `
CREATE TABLE IF NOT EXISTS customers (
  customer_id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT NOT NULL, signup_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  product_id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, unit_price REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  order_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, order_date TEXT NOT NULL, total_amount REAL NOT NULL,
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);
CREATE TABLE IF NOT EXISTS order_items (
  order_id INTEGER NOT NULL, product_id INTEGER NOT NULL, quantity INTEGER NOT NULL, unit_price REAL NOT NULL,
  PRIMARY KEY (order_id, product_id),
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);
`;

const SEED = `
INSERT OR IGNORE INTO customers VALUES
 (1,'东恒科技','华东','2023-01-15'),(2,'南方贸易','华南','2023-02-20'),
 (3,'北方制造','华北','2023-03-10'),(4,'西部实业','西南','2023-04-05');
INSERT OR IGNORE INTO products VALUES
 (1,'A 型组件','电子',120),(2,'B 型轴承','机械',85),
 (3,'C 型传感器','电子',210),(4,'D 型线缆','材料',45);
INSERT OR IGNORE INTO orders VALUES
 (1,1,'2024-01-12',1200),(2,2,'2024-02-08',850),(3,1,'2024-03-15',2100),
 (4,3,'2024-03-20',450),(5,2,'2024-04-01',1700),(6,4,'2024-05-02',1300);
INSERT OR IGNORE INTO order_items VALUES
 (1,1,10,120),(1,3,2,210),(2,2,10,85),(3,1,15,120),(3,4,5,45),
 (4,2,5,85),(5,3,5,210),(5,1,2,120),(6,4,10,45),(6,3,3,210);
`;

export function migrate(db: DbClient): void {
  db.execRaw(DDL);
  db.execRaw(SEED);
}
