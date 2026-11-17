import { Route, Routes } from "react-router";
import Layout from "./components/Layout";
import { UIProvider } from "./context/UIContext";
import Dashboard from "./pages/Dashboard";
import NewApplication from "./pages/NewApplication";
import Workspace from "./pages/Workspace";

export default function App() {
  return (
    <UIProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewApplication />} />
          <Route path="/applications/:ref" element={<Workspace />} />
        </Route>
      </Routes>
    </UIProvider>
  );
}
