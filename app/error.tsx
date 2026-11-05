'use client';
export default function ErrorPage({reset}:{reset:()=>void}){return <main className="empty"><h1>Не удалось открыть страницу</h1><p>Попробуйте загрузить данные ещё раз.</p><button className="btn primary" onClick={reset}>Повторить</button></main>;}
