import CheckinPage from "./pages/CheckinPage";
import TermsPage from "./pages/TermsPage";

export default function App() {
  if (window.location.pathname === "/terms") {
    return <TermsPage />;
  }

  return <CheckinPage />;
}
