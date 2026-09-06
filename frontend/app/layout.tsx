import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'L.I.R.A. · Command',
  description:
    'L.I.R.A. decision-support interface prototype. All operational data is simulated.',
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
