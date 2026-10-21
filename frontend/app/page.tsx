"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import {
  Activity, ArrowDownToLine, ArrowRight, Check, CheckCircle2, CircleHelp, Clock3,
  Download, ExternalLink, FileAudio, FileText, Filter, Github, Headphones, Link2,
  ListMusic, LoaderCircle, Music2, Pause, Play, Plus, RadioTower, RefreshCw,
  Search, Settings2, ShieldCheck, SlidersHorizontal, Sparkles, Square, Moon, Sun,
  Terminal, X, AlertTriangle, Pencil, ChevronDown, Music, Disc3
} from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
type Track = { n: number; reel: string; status: string; artist: string; song: string; youtube: string; alternatives: string; score: string; error: string; audio: string | null };
type Status = { total: number; recognized: number; downloaded: number; manual: number; unrecognized: number; errors: number };
type Job = { running: boolean; mode: string | null; started_at: string | null; exit_code: number | null; current_index: number; logs: string[] };
type State = { tracks: Track[]; counts: Status; job: Job };
const EMPTY: State = { tracks: [], counts: { total: 0, recognized: 0, downloaded: 0, manual: 0, unrecognized: 0, errors: 0 }, job: { running: false, mode: null, started_at: null, exit_code: null, current_index: 0, logs: [] } };
type View = "workspace" | "library" | "activity";
type Mode = "identify" | "search" | "download";
type FilterName = "all" | "downloaded" | "manual" | "unrecognized" | "identified";
const statusLabels: Record<string, string> = {
  DOWNLOADED: "Скачано", CHECK_MANUALLY: "Проверить", NOT_RECOGNIZED: "Не распознано",
  ERROR: "Ошибка", IDENTIFIED: "Распознано", FOUND_FULL_TRACK: "Полная версия найдена", STARTED: "В процессе"
};
function friendlyStatus(s: string) { return statusLabels[s] || "В очереди"; }
async function request<T>(route: string, method = "GET", body?: object): Promise<T> {
  const resp = await fetch(`${API}${route}`, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined, cache: "no-store" });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { const data = await resp.json(); detail = typeof data.detail === "string" ? data.detail : detail; } catch {}
    throw new Error(detail);
  }
  return resp.json();
}
function parseAlternatives(raw: string) {
  return raw.split(/\s\|\s/).map(part => {
    const m = part.match(/(https:\/\/www\.youtube\.com\/watch\?v=[\w-]+)/);
    return { title: part.replace(/\s*\(https:\/\/www\.youtube\.com\/watch\?v=[\w-]+\)/, ""), url: m?.[1] || "" };
  }).filter(c => c.title || c.url);
}
export default function Page() {
  const [data, setData] = useState<State>(EMPTY);
  const [connected, setConnected] = useState(false);
  const [view, setView] = useState<View>("workspace");
  const [mode, setMode] = useState<Mode>("identify");
  const [browser, setBrowser] = useState("chrome");
  const [isMac, setIsMac] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [filter, setFilter] = useState<FilterName>("all");
  const [search, setSearch] = useState("");
  const [linksText, setLinksText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [playing, setPlaying] = useState<number | null>(null);
  const [edit, setEdit] = useState<Track | null>(null);
  const [editedArtist, setEditedArtist] = useState("");
  const [editedSong, setEditedSong] = useState("");
  const [showAllLogs, setShowAllLogs] = useState(false);
  const [linksOpen, setLinksOpen] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const next = await request<State>("/api/state");
      setData(next); setConnected(true);
      setLinksText(previous => dirty ? previous : next.tracks.map(t => t.reel).join("\n"));
    } catch { setConnected(false); }
  }, [dirty]);
  useEffect(() => { refresh(); const id = setInterval(refresh, 2000); return () => clearInterval(id); }, [refresh]);
  useEffect(() => { setIsMac(navigator.platform.toLowerCase().includes("mac")); }, []);
  useEffect(() => {
    const saved = localStorage.getItem("reeltrack-theme");
    const initial = saved === "light" || saved === "dark"
      ? saved
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(initial);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("reeltrack-theme", theme);
  }, [theme]);
  useEffect(() => { if (!message) return; const id = setTimeout(() => setMessage(""), 6000); return () => clearTimeout(id); }, [message]);
  const trackList = useMemo(() => data.tracks.filter(t => {
    const term = search.toLocaleLowerCase().trim();
    const matched = !term || `${t.n} ${t.artist} ${t.song} ${t.reel}`.toLocaleLowerCase().includes(term);
    if (!matched) return false;
    if (filter === "downloaded") return t.status === "DOWNLOADED";
    if (filter === "manual") return t.status === "CHECK_MANUALLY";
    if (filter === "unrecognized") return t.status === "NOT_RECOGNIZED" || t.status === "ERROR";
    if (filter === "identified") return !!t.song && t.status !== "DOWNLOADED";
    return true;
  }), [data.tracks, search, filter]);
  const completed = data.counts.downloaded;
  const recognizedPercentage = data.counts.total ? Math.round(data.counts.recognized / data.counts.total * 100) : 0;
  const progress = data.counts.total ? Math.round(data.job.current_index / data.counts.total * 100) : 0;

  async function saveLinks(silent = false) {
    setLoading(true);
    try {
      const resp = await request<{ count: number; data: State }>("/api/reels", "POST", { text: linksText });
      setDirty(false); setData(resp.data); if (!silent) setMessage(`Сохранено ${resp.count} ссылок`);
      return true;
    } catch (e) { setMessage(e instanceof Error ? e.message : "Не удалось сохранить ссылки"); return false; }
    finally { setLoading(false); }
  }
  async function start() {
    if (dirty && !(await saveLinks(true))) return;
    setLoading(true);
    try { await request("/api/run", "POST", { mode, browser }); setMessage("Обработка запущена"); await refresh(); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Не удалось запустить"); }
    finally { setLoading(false); }
  }
  async function stop() {
    try { await request("/api/stop", "POST"); setMessage("Останавливаю обработку…"); }
    catch (e) { setMessage(e instanceof Error ? e.message : "Ошибка остановки"); }
  }
  async function saveEdit() {
    if (!edit) return;
    setLoading(true);
    try {
      const next = await request<State>(`/api/tracks/${edit.n}`, "PATCH", { artist: editedArtist, song: editedSong });
      setData(next); setEdit(null); setMessage("Название сохранено. Повторный поиск использует исправленную песню.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "Не удалось сохранить название"); }
    finally { setLoading(false); }
  }
  function openEdit(track: Track) { setEdit(track); setEditedArtist(track.artist); setEditedSong(track.song); }
  function download(kind: "songs" | "names" | "results") { window.open(`${API}/api/export/${kind}`, "_blank", "noopener,noreferrer"); }
  const snippets = showAllLogs ? data.job.logs : data.job.logs.slice(-8);

  return <div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Music2 size={23} strokeWidth={2.1}/></div><div><div className="brand-title">reeltrack<span>.</span></div><div className="brand-sub">МУЗЫКА ИЗ REELS</div></div></div>
      <div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav className="navigation">
        <button className={view === "workspace" ? "nav-item active" : "nav-item"} onClick={() => setView("workspace")}><SlidersHorizontal size={18}/> Обзор</button>
        <button className={view === "library" ? "nav-item active" : "nav-item"} onClick={() => setView("library")}><ListMusic size={18}/> Медиатека <span className="nav-count">{data.counts.total}</span></button>
        <button className={view === "activity" ? "nav-item active" : "nav-item"} onClick={() => setView("activity")}><Terminal size={18}/> Активность</button>
      </nav>
      <div className="sidebar-spacer" />
      <div className="local-card"><div className="local-head"><ShieldCheck size={18}/><span>Локальный режим</span></div><p>Аудиофайлы и cookies остаются на этом компьютере.</p><span className="local-foot"><span className="green-dot"/> Никакого облака</span></div>
      <div className="sidebar-bottom"><span className={connected ? "live-dot" : "offline-dot"}/>{connected ? "Python API подключён" : "Python API отключён"}<span className="version">v0.1</span></div>
    </aside>

    <main className="main">
      <header className="topbar"><div className="breadcrumbs">Студия <span>/</span> <strong>{view === "workspace" ? "Обзор" : view === "library" ? "Медиатека" : "Активность"}</strong></div><div className="top-actions"><Button variant="ghost" size="icon" className="icon-action" title={theme === "dark" ? "Светлая тема" : "Тёмная тема"} aria-label={theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"} onClick={() => setTheme(current => current === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={17}/> : <Moon size={17}/>}</Button><Button variant="ghost" size="icon" className="icon-action" title="Обновить" onClick={refresh}><RefreshCw size={17}/></Button></div></header>
      {!connected && <div className="offline-banner"><AlertTriangle size={18}/> Нет подключения к Python API. Запусти сервер на <code>127.0.0.1:8000</code> — инструкция в README проекта.</div>}

      {view === "workspace" && <motion.div className="content" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}>
        <section className="hero"><div className="eyebrow"><span className="eyebrow-line"/> МУЗЫКА ИЗ REELS</div><h1>Узнай, что играет.<br/><span>Сохрани любимое.</span></h1><p>Распознавай песни из Instagram Reels и собирай полные версии в своей медиатеке.</p><div className="hero-foot"><Music2 size={15}/><span>Ссылки и найденные треки — в одном месте</span></div><div className="hero-art"><div className="record-ring one"/><div className="record-ring two"/><div className="record-core"><Music2 size={42}/></div></div></section>

        <section className="stat-grid">
          <Metric title="Всего Reels" value={data.counts.total} icon={<Link2 size={19}/>} detail="Добавлено в очередь" />
          <Metric title="Распознано" value={data.counts.recognized} icon={<Sparkles size={19}/>} detail={`${recognizedPercentage}% всех ссылок`} accent="mint"/>
          <Metric title="MP3 готово" value={completed} icon={<FileAudio size={19}/>} detail="Успешных позиций" accent="blue"/>
          <Metric title="Нужна проверка" value={data.counts.manual + data.counts.unrecognized + data.counts.errors} icon={<CircleHelp size={19}/>} detail="Для ручного поиска" accent="amber"/>
        </section>
        <section className="split-layout"><div className="panel collection-panel"><div className="panel-heading"><div><div className="section-kicker">ИСТОЧНИК</div><h2>Ссылки на Reels</h2></div><button className="text-button" onClick={() => setLinksOpen(!linksOpen)}>{linksOpen ? "Свернуть" : "Развернуть"}<ChevronDown size={15} className={linksOpen ? "up" : ""}/></button></div>
          {linksOpen && <><p className="panel-caption">Вставь ссылки по одной на строку. Повторы автоматически удаляются.</p><div className="textarea-wrap"><textarea spellCheck={false} value={linksText} onChange={e => { setLinksText(e.target.value); setDirty(true); }} placeholder={"https://www.instagram.com/reel/...\nhttps://www.instagram.com/reel/..."}/><span className="textarea-count">{linksText.split(/\n/).filter(x=>x.trim()).length} строк</span></div><div className="collection-actions"><button className="secondary-button" disabled={!dirty || loading || data.job.running} onClick={() => saveLinks()}><Check size={15}/> Сохранить ссылки</button><span>Сохраняется только на компьютере</span></div></>}
        </div><div className="panel action-panel"><div className="panel-heading"><div><div className="section-kicker">ОБРАБОТКА</div><h2>Запустить обработку</h2></div><span className="step-icon"><Settings2 size={18}/></span></div><div className="form-row"><label htmlFor="mode">Режим обработки</label><div className="select-wrap"><select id="mode" value={mode} onChange={e => setMode(e.target.value as Mode)} disabled={data.job.running}><option value="identify">Распознать названия</option><option value="search">Найти полные версии</option><option value="download">Скачать полные MP3</option></select><ChevronDown size={16}/></div></div><div className="form-row"><label htmlFor="browser">Браузер для авторизации</label><div className="select-wrap"><select id="browser" value={browser} onChange={e=>setBrowser(e.target.value)} disabled={data.job.running}><option value="chrome">Chrome</option><option value="firefox">Firefox</option><option value="edge">Edge</option><option value="brave">Brave</option><option value="zen">Zen Browser</option>{isMac && <option value="safari">Safari</option>}<option value="none">Без cookies</option></select><ChevronDown size={16}/></div></div><div className="run-actions">{data.job.running ? <button className="danger-button" onClick={stop}><Square size={15} fill="currentColor"/> Остановить</button> : <button className="primary-button" onClick={start} disabled={!connected || loading || (!data.counts.total && !linksText.trim())}><Play size={16} fill="currentColor"/> Запустить <ArrowRight size={17}/></button>}</div><p className="safe-note"><ShieldCheck size={15}/> Скачивай только записи, на которые у тебя есть права.</p></div></section>

        {(data.job.running || data.job.current_index > 0) && <section className="progress-panel"><div className="progress-header"><div><span className="pulse-dot"/> {data.job.running ? "Обработка выполняется" : "Последняя обработка"}</div><strong>{data.job.current_index} / {data.counts.total}</strong></div><div className="progress-track"><div style={{width:`${progress}%`}}/></div><span className="progress-sub">{data.job.running ? "Результаты обновляются автоматически" : "Можно продолжить с сохранёнными результатами"}</span></section>}

        <LibrarySection tracks={trackList} allCount={data.counts.total} filter={filter} setFilter={setFilter} search={search} setSearch={setSearch} playing={playing} setPlaying={setPlaying} openEdit={openEdit} download={download}/>
        <Logs lines={snippets} showAll={showAllLogs} setShowAll={setShowAllLogs} active={data.job.running}/>
      </motion.div>}

      {view === "library" && <motion.div className="content page-view" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}><div className="view-title"><div className="eyebrow">ТВОИ ТРЕКИ</div><h1>Медиатека <span>ReelTrack</span></h1><p>Распознанные песни, кандидаты и сохранённые MP3.</p></div><LibrarySection tracks={trackList} allCount={data.counts.total} filter={filter} setFilter={setFilter} search={search} setSearch={setSearch} playing={playing} setPlaying={setPlaying} openEdit={openEdit} download={download}/></motion.div>}
      {view === "activity" && <motion.div className="content page-view" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}><div className="view-title"><div className="eyebrow">ИСТОРИЯ ЗАДАЧ</div><h1>Журнал <span>обработки</span></h1><p>Ход и результаты последней обработки ссылок.</p></div><Logs lines={data.job.logs} showAll setShowAll={()=>{}} active={data.job.running} large/></motion.div>}
    </main>
    {message && <div className="toast"><CircleHelp size={16}/>{message}<button onClick={() => setMessage("")}><X size={15}/></button></div>}
    {edit && <div className="modal-backdrop" onClick={() => setEdit(null)}><div className="modal" onClick={e=>e.stopPropagation()}><div className="modal-top"><h2>Исправить песню #{edit.n}</h2><button onClick={()=>setEdit(null)}><X size={19}/></button></div><p>Введи проверенное название. При следующем запуске поиска скрипт использует его.</p><label>Исполнитель<input value={editedArtist} onChange={e=>setEditedArtist(e.target.value)} placeholder="Название исполнителя"/></label><label>Песня<input value={editedSong} onChange={e=>setEditedSong(e.target.value)} placeholder="Название композиции"/></label><div className="modal-actions"><button className="secondary-button" onClick={()=>setEdit(null)}>Отмена</button><button className="primary-button" disabled={!editedArtist.trim() || !editedSong.trim() || loading} onClick={saveEdit}><Check size={16}/> Сохранить</button></div></div></div>}
  </div>;
}

function Metric({title,value,detail,icon,accent=""}: {title:string,value:number,detail:string,icon:React.ReactNode,accent?:string}) {
  return <div className={`metric ${accent}`}><div className="metric-head"><span>{title}</span><span className="metric-icon">{icon}</span></div><strong>{value.toString().padStart(2,"0")}</strong><div className="metric-detail"><span className="metric-line"/>{detail}</div></div>;
}
function LibrarySection({tracks,allCount,filter,setFilter,search,setSearch,playing,setPlaying,openEdit,download}: {
  tracks:Track[],allCount:number,filter:FilterName,setFilter:(s:FilterName)=>void,search:string,setSearch:(s:string)=>void,
  playing:number|null,setPlaying:(n:number|null)=>void,openEdit:(t:Track)=>void,download:(k:"songs"|"names"|"results")=>void
}) {
  const tabs: {value:FilterName,label:string}[] = [{value:"all",label:"Все"},{value:"downloaded",label:"MP3"},{value:"identified",label:"Распознано"},{value:"manual",label:"На проверку"},{value:"unrecognized",label:"Не определено"}];
  return <section className="panel library-panel"><div className="library-heading"><div><div className="section-kicker">МЕДИАТЕКА</div><h2>Твоя медиатека <span className="little-count">{allCount}</span></h2><p>Прослушивай, проверяй и сохраняй найденные песни.</p></div><div className="export-actions"><button onClick={()=>download("names")} title="Экспорт названий"><FileText size={16}/> TXT</button><button onClick={()=>download("songs")} title="Экспорт таблицы"><Download size={16}/> CSV</button></div></div>
    <div className="library-toolbar"><div className="filters">{tabs.map(t=><button key={t.value} className={filter===t.value?"filter active":"filter"} onClick={()=>setFilter(t.value)}>{t.label}</button>)}</div><div className="search-wrap"><Search size={17}/><input placeholder="Найти песню..." value={search} onChange={e=>setSearch(e.target.value)}/></div></div>
    <div className="table-scroll"><table className="track-table"><thead><tr><th className="th-num">#</th><th>КОМПОЗИЦИЯ</th><th>СТАТУС</th><th className="th-actions">ДЕЙСТВИЯ</th></tr></thead><tbody>{tracks.map(t=><TrackRow key={t.n} t={t} playing={playing} setPlaying={setPlaying} openEdit={openEdit}/>)}</tbody></table>{!tracks.length&&<div className="empty"><ListMusic size={28}/><h3>Пока здесь пусто</h3><p>{allCount ? "Попробуй другой фильтр или поисковый запрос." : "Добавь Instagram Reels и запусти распознавание."}</p></div>}</div>
    <div className="table-footer"><span>Показано {tracks.length} из {allCount}</span><span><span className="green-dot"/> Сохраняется локально</span></div>
  </section>;
}
function TrackRow({t,playing,setPlaying,openEdit}:{t:Track,playing:number|null,setPlaying:(n:number|null)=>void,openEdit:(t:Track)=>void}){
  const alternatives = parseAlternatives(t.alternatives);
  const isPlaying = playing === t.n;
  return <><tr><td className="track-n">{String(t.n).padStart(2,"0")}</td><td><div className="track-name"><span className={t.audio ? "track-cover ready" : "track-cover"}><Music2 size={18}/></span><div className="track-info"><strong>{t.song || "Название не определено"}</strong><span>{t.artist || "Открой Reel и уточни песню"}</span></div></div></td><td><span className={`status status-${t.status.toLowerCase() || "idle"}`}><span/>{friendlyStatus(t.status)}</span></td><td><div className="track-actions">{(t.audio || t.alternatives) && <button title={isPlaying?"Закрыть подробности":t.audio?"Слушать MP3":"Посмотреть кандидатов"} onClick={()=>setPlaying(isPlaying?null:t.n)}>{isPlaying?<Pause size={16}/>:t.audio?<Play size={16}/>:<CircleHelp size={16}/>}</button>}<button title="Исправить название" onClick={()=>openEdit(t)}><Pencil size={16}/></button><a title="Instagram Reel" href={t.reel} target="_blank" rel="noreferrer"><ExternalLink size={16}/></a>{(t.youtube || (t.song && t.artist)) && <a title="Найти полную песню на YouTube" href={t.youtube || `https://www.youtube.com/results?search_query=${encodeURIComponent(`${t.artist} ${t.song}`)}`} target="_blank" rel="noreferrer"><Headphones size={16}/></a>}</div></td></tr>
    {(isPlaying || (t.status==="CHECK_MANUALLY" && alternatives.length>0 && isPlaying)) && <tr className="expanded-row"><td colSpan={4}><div className="inline-panel">{t.audio && <audio controls autoPlay src={`${API}${t.audio}`}/>}<div className="suggestions">{alternatives.slice(0,3).map((a,i)=>a.url&&<a key={i} href={a.url} target="_blank" rel="noreferrer">Кандидат {i+1}: {a.title} <ExternalLink size={12}/></a>)}</div>{t.error&&<small>{t.error}</small>}</div></td></tr>}
  </>;
}
function Logs({lines,showAll,setShowAll,active,large=false}:{lines:string[],showAll:boolean,setShowAll:(b:boolean)=>void,active:boolean,large?:boolean}){
  return <section className={`panel logs-panel ${large?"full-logs":""}`}><div className="logs-head"><div><span className="terminal-icon"><Terminal size={18}/></span><strong>Журнал операций</strong><span className="small-label">ПОСЛЕДНИЕ СОБЫТИЯ</span></div>{active?<span className="running-indicator"><LoaderCircle size={14} className="spin"/> Выполняется</span>:!large?<button onClick={()=>setShowAll(!showAll)} className="text-button">{showAll?"Свернуть":"Все записи"}<ArrowRight size={14}/></button>:null}</div><div className="log-body">{lines.length?lines.map((line,i)=><div key={i} className={line.includes("→ DOWNLOADED")?"log-success":line.includes("ERROR")||line.includes("Ошибка")?"log-error":""}><span className="log-chevron">›</span>{line}</div>):<div className="log-empty">› Пока нет операций. Запусти обработку, и здесь появится её ход.</div>}</div></section>;
}
