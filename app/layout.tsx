import type { Metadata } from 'next';
import localFont from 'next/font/local';
import './globals.css';
const manrope = localFont({ src: './fonts/Manrope.ttf', weight: '200 800', display: 'swap', variable: '--font-manrope' });
export const metadata:Metadata = {title:'Заявка — школьный сервис',description:'Рабочий кабинет школьной службы заявок'};
export default function RootLayout({children}:{children:React.ReactNode}) { return <html lang="ru" className={manrope.variable}><body>{children}</body></html>; }
