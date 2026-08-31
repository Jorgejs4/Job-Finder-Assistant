import "./globals.css";
import type { ReactNode } from "react";

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="es"><body>{children}<style>{`.advanced{flex-wrap:wrap}.advanced input{min-width:210px}.advanced .small-input{min-width:115px;width:115px}.settings{max-width:760px}.settings label{display:grid;gap:7px;margin:16px 0;color:#475569;font-weight:600}.settings input{border:1px solid #dce2eb;border-radius:9px;padding:11px;background:#fff;font-weight:400}.form-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:0 18px}.settings label:has(input[type=checkbox]){display:flex;align-items:center;gap:8px}.settings label:has(input[type=checkbox]) input{width:auto}.success{color:#15803d!important}@media(max-width:700px){.form-grid{grid-template-columns:1fr}.advanced input{min-width:100%}.advanced .small-input{width:100%;min-width:100%}}`}</style></body></html>;
}
