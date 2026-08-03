import { BrowserRouter } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DataSourcePicker } from "./components/DataSourcePicker";
import { DataSourceProvider } from "./dataSourceStore";
import { AppRoutes } from "./routes";

export const App = () => (
  <BrowserRouter>
    <DataSourceProvider>
      <AppShell toolbar={<DataSourcePicker />}>
        <AppRoutes />
      </AppShell>
    </DataSourceProvider>
  </BrowserRouter>
);
