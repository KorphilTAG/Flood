import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'Flood · Command',
  description:
    'Flood decision-support interface prototype. All operational data is simulated.',
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
