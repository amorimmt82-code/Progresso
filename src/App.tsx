import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Trash2, LayoutGrid, Table as TableIcon, ChevronRight, ChevronDown, Download, ArrowUp, ArrowDown, ArrowUpDown, Radio, Wifi, WifiOff, RefreshCw, Package, BarChart3, List } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import * as XLSX from 'xlsx';
import { parseExcel, groupData, type ProductionData, type SessionData, type GroupedData, formatMsToDuration } from './utils/excel';

const API_BASE = import.meta.env.VITE_API_URL || '';

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

function roundCpm(cpm: number) {
  return Number(cpm.toFixed(2));
}

function getCpmStyles(cpm: number) {
  const roundedCpm = roundCpm(cpm);

  if (roundedCpm >= 1.4) {
    return {
      badge: 'bg-emerald-50 text-emerald-700 border-emerald-100',
      accent: 'border-l-4 border-l-emerald-400',
    };
  }
  if (roundedCpm >= 1.19) {
    return {
      badge: 'bg-yellow-50 text-yellow-700 border-yellow-100',
      accent: 'border-l-4 border-l-yellow-400',
    };
  }
  return {
    badge: 'bg-red-50 text-red-700 border-red-100',
    accent: 'border-l-4 border-l-red-400',
  };
}

type ProductionSlotEntry = {
  timeRange?: string;
  registeredAt?: string;
  cpm?: number;
  punnets?: number;
  _timeRange?: string;
  _registeredAt?: string;
  _cpm?: number;
  _punnets?: number;
  'Registered at'?: string | Date;
};

type SessionSlotEntry = {
  loginTime?: string;
  logoutTime?: string;
  device?: string;
  'Login time'?: string | Date;
  'Logout time'?: string | Date;
  Device?: string;
};

function getProductionTimeLabel(entry: ProductionSlotEntry) {
  const explicitRange = entry.timeRange || entry._timeRange;
  if (explicitRange) {
    return explicitRange;
  }

  const registeredAt = entry['Registered at'];
  if (registeredAt instanceof Date) {
    return registeredAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  return typeof registeredAt === 'string' && registeredAt ? registeredAt : '-';
}

function getProductionPunnets(entry: ProductionSlotEntry) {
  return Number(entry.punnets ?? entry._punnets ?? 0);
}

function parseClockMinutes(value: string) {
  const match = value.match(/(\d{2}):(\d{2})/);
  if (!match) {
    return null;
  }

  return Number(match[1]) * 60 + Number(match[2]);
}

function parseTimeRange(value: string) {
  const match = value.match(/(\d{2}:\d{2})\s*[^\d]+\s*(\d{2}:\d{2})/);
  if (!match) {
    return null;
  }

  const start = parseClockMinutes(match[1]);
  const end = parseClockMinutes(match[2]);
  if (start === null || end === null) {
    return null;
  }

  return { start, end: end > start ? end : end + 24 * 60 };
}

function toSessionDate(value?: string | Date) {
  if (!value) {
    return null;
  }

  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getDateRangeWorkingMinutes(start: Date, end: Date, sessionEntries: SessionSlotEntry[]) {
  const clippedIntervals: Array<[number, number]> = [];

  for (const session of sessionEntries) {
    const login = toSessionDate(session.loginTime ?? session['Login time']);
    if (!login) {
      continue;
    }

    const logout = toSessionDate(session.logoutTime ?? session['Logout time']) ?? new Date();
    const overlapStart = Math.max(start.getTime(), login.getTime());
    const overlapEnd = Math.min(end.getTime(), logout.getTime());
    if (overlapEnd > overlapStart) {
      clippedIntervals.push([overlapStart, overlapEnd]);
    }
  }

  if (clippedIntervals.length === 0) {
    return 0;
  }

  clippedIntervals.sort((left, right) => left[0] - right[0]);
  const merged: Array<[number, number]> = [clippedIntervals[0]];
  for (const interval of clippedIntervals.slice(1)) {
    const last = merged[merged.length - 1];
    if (interval[0] <= last[1]) {
      last[1] = Math.max(last[1], interval[1]);
    } else {
      merged.push([...interval]);
    }
  }

  return merged.reduce((total, [startMs, endMs]) => total + ((endMs - startMs) / 60000), 0);
}

function getClockRangeWorkingMinutes(rangeStart: number, rangeEnd: number, sessionEntries: SessionSlotEntry[]) {
  const clippedIntervals: Array<[number, number]> = [];

  for (const session of sessionEntries) {
    const login = toSessionDate(session.loginTime ?? session['Login time']);
    if (!login) {
      continue;
    }

    const logout = toSessionDate(session.logoutTime ?? session['Logout time']) ?? new Date();
    let sessionStart = login.getHours() * 60 + login.getMinutes() + login.getSeconds() / 60;
    let sessionEnd = logout.getHours() * 60 + logout.getMinutes() + logout.getSeconds() / 60;
    if (sessionEnd <= sessionStart) {
      sessionEnd += 24 * 60;
    }

    const overlapStart = Math.max(rangeStart, sessionStart);
    const overlapEnd = Math.min(rangeEnd, sessionEnd);
    if (overlapEnd > overlapStart) {
      clippedIntervals.push([overlapStart, overlapEnd]);
    }
  }

  if (clippedIntervals.length === 0) {
    return 0;
  }

  clippedIntervals.sort((left, right) => left[0] - right[0]);
  const merged: Array<[number, number]> = [clippedIntervals[0]];
  for (const interval of clippedIntervals.slice(1)) {
    const last = merged[merged.length - 1];
    if (interval[0] <= last[1]) {
      last[1] = Math.max(last[1], interval[1]);
    } else {
      merged.push([...interval]);
    }
  }

  return merged.reduce((total, [start, end]) => total + (end - start), 0);
}

function getProductionReferenceDate(entry: ProductionSlotEntry) {
  const rawRegisteredAt = entry.registeredAt ?? entry._registeredAt;
  if (rawRegisteredAt) {
    return toSessionDate(rawRegisteredAt);
  }

  const registeredAt = entry['Registered at'];
  if (registeredAt instanceof Date) {
    return registeredAt;
  }

  if (typeof registeredAt === 'string' && registeredAt.includes('T')) {
    return toSessionDate(registeredAt);
  }

  return null;
}

function getProductionEntryCpm(entry: ProductionSlotEntry, sessionEntries: SessionSlotEntry[], fallbackCpm = 0) {
  const inlineCpm = Number(entry.cpm ?? entry._cpm);
  if (Number.isFinite(inlineCpm) && inlineCpm > 0) {
    return roundCpm(inlineCpm);
  }

  const punnets = getProductionPunnets(entry);
  if (punnets <= 0) {
    return 0;
  }

  const timeRange = getProductionTimeLabel(entry);
  const parsedRange = parseTimeRange(timeRange);
  if (!parsedRange) {
    return roundCpm(fallbackCpm);
  }

  const referenceDate = getProductionReferenceDate(entry);
  if (referenceDate) {
    const start = new Date(referenceDate);
    start.setHours(Math.floor(parsedRange.start / 60) % 24, parsedRange.start % 60, 0, 0);
    const end = new Date(start);
    end.setMinutes(end.getMinutes() + (parsedRange.end - parsedRange.start));
    const workingMinutes = getDateRangeWorkingMinutes(start, end, sessionEntries);
    if (workingMinutes > 0) {
      return roundCpm(punnets / workingMinutes);
    }
  }

  const workingMinutes = getClockRangeWorkingMinutes(parsedRange.start, parsedRange.end, sessionEntries);
  if (workingMinutes > 0) {
    return roundCpm(punnets / workingMinutes);
  }

  const slotDuration = parsedRange.end - parsedRange.start;
  if (slotDuration > 0) {
    return roundCpm(punnets / slotDuration);
  }

  return roundCpm(fallbackCpm);
}

function getOperatorIdentityKey(entry: { user?: string; device?: string; nrIdentificacao?: string; cdRcsHumano?: string }) {
  const user = (entry.user || '').trim();
  const cdRcsHumano = (entry.cdRcsHumano || '').trim();
  const nrIdentificacao = (entry.nrIdentificacao || '').trim();
  if (cdRcsHumano || nrIdentificacao) {
    return `${user}|${cdRcsHumano}|${nrIdentificacao}`;
  }
  return `${user}|${(entry.device || '').trim()}`;
}

function getSessionDeviceLabel(session: { Device?: string; device?: string }, fallbackDevice = '') {
  return (session.Device || session.device || fallbackDevice || '').trim();
}

type SortField = 'user' | 'device' | 'totalWeight' | 'totalWorkingTimeMs' | 'totalSessions' | 'productionCount' | 'punnets' | 'cpm' | 'nrIdentificacao' | 'cdRcsHumano' | 'bloqueios';
type SortOrder = 'asc' | 'desc';

interface SortConfig {
  field: SortField;
  order: SortOrder;
}

type AppMode = 'live' | 'history';
type ViewMode = 'geral' | 'grafico' | 'registros';

interface LiveStats {
  productionEntries: number;
  sessionEntries: number;
  groupedCount: number;
  scanCount: number;
  filesFound: { name: string; type: string; rows: number; modified: string }[];
  lastScan: number | null;
}

interface LiveGroupedEntry {
  user: string;
  device: string;
  totalWeight: number;
  totalSessions: number;
  totalWorkingTimeMs: number;
  totalPunnets: number;
  bloqueios: number;
  articles: string[];
  customers: string[];
  currentArticle: string;
  currentCustomer: string;
  nrIdentificacao: string;
  cdRcsHumano: string;
  cpm: number;
  productionEntries: {
    articleName: string;
    timeRange: string;
    registeredAt: string;
    endedAt?: string;
    cpm?: number;
    punnets: number;
    netWeight: number;
    avgWeight: number;
    deviceName: string;
    customerName: string;
  }[];
  sessionEntries: {
    activity: string;
    loginTime: string;
    logoutTime: string;
    workingTime: string;
    line: string;
    device: string;
  }[];
}

export default function App() {
  const [mode, setMode] = useState<AppMode>('live');
  const [productionFiles, setProductionFiles] = useState<File[]>([]);
  const [sessionFiles, setSessionFiles] = useState<File[]>([]);
  const [productionData, setProductionData] = useState<ProductionData[]>([]);
  const [sessionData, setSessionData] = useState<SessionData[]>([]);
  const [groupedResults, setGroupedResults] = useState<GroupedData[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [isUploadVisible, setIsUploadVisible] = useState(true);
  const [sortConfig, setSortConfig] = useState<SortConfig | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('geral');
  const [chartSelectedOps, setChartSelectedOps] = useState<Set<string>>(new Set());
  const [registrosExpandedOps, setRegistrosExpandedOps] = useState<Set<string>>(new Set());
  const [chartFullscreen, setChartFullscreen] = useState(false);
  const [registrosVisibleCounts, setRegistrosVisibleCounts] = useState<Record<string, number>>({});
  const [historyViewMode, setHistoryViewMode] = useState<ViewMode>('geral');

  // Live mode state
  const [liveData, setLiveData] = useState<LiveGroupedEntry[]>([]);
  const [liveStats, setLiveStats] = useState<LiveStats | null>(null);
  const [isLiveConnected, setIsLiveConnected] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevArticlesRef = useRef<string | null>(null);
  const exportTriggeredRef = useRef(false);
  const [expandedSlots, setExpandedSlots] = useState<Set<string>>(new Set());
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);
  const [processoBanner, setProcessoBanner] = useState('');
  const [lojaBanner, setLojaBanner] = useState('');

  // History mode state
  const [historyData, setHistoryData] = useState<LiveGroupedEntry[]>([]);
  const [historyStats, setHistoryStats] = useState<LiveStats | null>(null);
  const [historyDate, setHistoryDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().split('T')[0];
  });
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyProcesso, setHistoryProcesso] = useState('');
  const [historyLoja, setHistoryLoja] = useState('');
  const [showInactiveOps, setShowInactiveOps] = useState(false);
  const inactiveOpsRef = useRef<HTMLDivElement>(null);

  // Range mode: 'day' = single date | 'week' = Mon-Sun | 'range' = start-end
  type HistoryRangeMode = 'day' | 'week' | 'range';
  const [historyRangeMode, setHistoryRangeMode] = useState<HistoryRangeMode>('day');
  const [historyEndDate, setHistoryEndDate] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);
    return d.toISOString().split('T')[0];
  });
  interface DaySummary { date: string; totalPunnets: number; totalWeight: number; operatorCount: number; processoBanner: string; }
  const [historyDays, setHistoryDays] = useState<DaySummary[]>([]);

  // Helper: get Mon-Sun for a given date
  const getWeekRange = (dateStr: string) => {
    const d = new Date(dateStr + 'T12:00:00');
    const day = d.getDay();
    const diffToMon = day === 0 ? -6 : 1 - day;
    const mon = new Date(d);
    mon.setDate(d.getDate() + diffToMon);
    const sun = new Date(mon);
    sun.setDate(mon.getDate() + 6);
    return { start: mon.toISOString().split('T')[0], end: sun.toISOString().split('T')[0] };
  };

  // Close export menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
      if (inactiveOpsRef.current && !inactiveOpsRef.current.contains(e.target as Node)) {
        setShowInactiveOps(false);
      }
    };
    if (showExportMenu || showInactiveOps) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showExportMenu, showInactiveOps]);

  // Fetch history data when date changes or entering history mode
  const fetchHistoryData = useCallback(async (date: string) => {
    setHistoryLoading(true);
    setHistoryDays([]);
    try {
      const res = await fetch(`${API_BASE}/api/history?date=${date}`);
      if (!res.ok) throw new Error('Falha ao buscar histórico');
      const json = await res.json();
      setHistoryData(json.grouped || []);
      setHistoryStats(json.stats || null);
      setHistoryProcesso(json.processoBanner || '');
      setHistoryLoja(json.lojaBanner || '');
      setError(null);
    } catch {
      setHistoryData([]);
      setHistoryStats(null);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Fetch history range data
  const fetchHistoryRange = useCallback(async (start: string, end: string) => {
    setHistoryLoading(true);
    setHistoryDays([]);
    try {
      const res = await fetch(`${API_BASE}/api/history/range?start=${start}&end=${end}`);
      if (!res.ok) throw new Error('Falha ao buscar intervalo');
      const json = await res.json();
      setHistoryData(json.combined || []);
      setHistoryStats(null);
      setHistoryProcesso('');
      setHistoryLoja('');
      setHistoryDays((json.days || []).map((d: any) => ({
        date: d.date,
        totalPunnets: d.totalPunnets,
        totalWeight: d.totalWeight,
        operatorCount: d.operatorCount,
        processoBanner: d.processoBanner,
      })));
      setError(null);
    } catch {
      setHistoryData([]);
      setHistoryStats(null);
      setHistoryDays([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (mode === 'history') {
      if (historyRangeMode === 'day') {
        fetchHistoryData(historyDate);
      } else if (historyRangeMode === 'week') {
        const { start, end } = getWeekRange(historyDate);
        fetchHistoryRange(start, end);
      } else if (historyRangeMode === 'range') {
        fetchHistoryRange(historyDate, historyEndDate);
      }
    }
  }, [mode, historyDate, historyEndDate, historyRangeMode, fetchHistoryData, fetchHistoryRange]);

  // Fetch live data from backend
  const fetchLiveData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/data`);
      if (!res.ok) throw new Error('Falha ao buscar dados');
      const json = await res.json();
      setLiveData(json.grouped || []);
      setLiveStats(json.stats || null);
      setProcessoBanner(json.processoBanner || '');
      setLojaBanner(json.lojaBanner || '');
      setIsLiveConnected(true);
      setError(null);
    } catch {
      setIsLiveConnected(false);
    }
  }, []);

  // Auto-refresh every 5 seconds in live mode only
  useEffect(() => {
    if (mode === 'live') {
      fetchLiveData();
      intervalRef.current = setInterval(fetchLiveData, 5000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [mode, fetchLiveData]);

  const handleFileUpload = useCallback(async (files: FileList | File[], type: 'production' | 'session') => {
    setIsLoading(true);
    setError(null);
    const fileArray = Array.from(files);
    
    try {
      const newData: any[] = [];
      for (const file of fileArray) {
        const data = await parseExcel<any>(file);
        newData.push(...data);
      }

      if (type === 'production') {
        setProductionData(prev => [...prev, ...newData]);
        setProductionFiles(prev => [...prev, ...fileArray]);
      } else {
        setSessionData(prev => [...prev, ...newData]);
        setSessionFiles(prev => [...prev, ...fileArray]);
      }
    } catch (err) {
      console.error(err);
      setError(`Erro ao processar arquivos ${type === 'production' ? 'de produção' : 'de sessões'}. Verifique o formato.`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const removeFile = async (index: number, type: 'production' | 'session') => {
    setIsLoading(true);
    try {
      if (type === 'production') {
        const newFiles = productionFiles.filter((_, i) => i !== index);
        setProductionFiles(newFiles);
        const allData: ProductionData[] = [];
        for (const file of newFiles) {
          const data = await parseExcel<ProductionData>(file);
          allData.push(...data);
        }
        setProductionData(allData);
      } else {
        const newFiles = sessionFiles.filter((_, i) => i !== index);
        setSessionFiles(newFiles);
        const allData: SessionData[] = [];
        for (const file of newFiles) {
          const data = await parseExcel<SessionData>(file);
          allData.push(...data);
        }
        setSessionData(allData);
      }
    } catch (err) {
      setError("Erro ao atualizar lista de arquivos.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleGroupData = () => {
    if (productionData.length === 0 || sessionData.length === 0) {
      setError('Por favor, carregue arquivos em ambos os campos para agrupar os dados.');
      return;
    }
    const results = groupData(productionData, sessionData);
    setGroupedResults(results);
    setIsUploadVisible(false); // Collapse after grouping
  };

  const toggleRow = (id: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedRows(newExpanded);
  };

  const requestSort = (field: SortField) => {
    let order: SortOrder = 'asc';
    if (sortConfig && sortConfig.field === field && sortConfig.order === 'asc') {
      order = 'desc';
    }
    setSortConfig({ field, order });
  };

  const getSortedResults = () => {
    const source = mode === 'live' ? liveDataAsGrouped : historyDataAsGrouped;
    const rawSource = mode === 'live' ? liveData : historyData;
    if (!sortConfig) return source;

    const sorted = [...source].sort((a, b) => {
      const field = sortConfig.field;
      let aVal: any = a[field as keyof GroupedData];
      let bVal: any = b[field as keyof GroupedData];

      if (field === 'productionCount') {
        aVal = a.productionEntries.length;
        bVal = b.productionEntries.length;
      }
      if (field === 'punnets') {
        const aLive = rawSource.find(l => getOperatorIdentityKey(l) === getOperatorIdentityKey(a));
        const bLive = rawSource.find(l => getOperatorIdentityKey(l) === getOperatorIdentityKey(b));
        aVal = aLive?.totalPunnets ?? a.productionEntries.reduce((s, p) => s + ((p as any)._punnets ?? 0), 0);
        bVal = bLive?.totalPunnets ?? b.productionEntries.reduce((s, p) => s + ((p as any)._punnets ?? 0), 0);
      }

      if (aVal < bVal) return sortConfig.order === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.order === 'asc' ? 1 : -1;
      return 0;
    });

    return sorted;
  };

  // Convert live data to GroupedData format
  const toGroupedData = (entry: LiveGroupedEntry): GroupedData => ({
    user: entry.user,
    device: entry.device,
    totalWeight: entry.totalWeight,
    totalSessions: entry.totalSessions,
    totalWorkingTimeMs: entry.totalWorkingTimeMs,
    bloqueios: entry.bloqueios,
    articles: entry.articles,
    customers: entry.customers || [],
    currentArticle: entry.currentArticle || '',
    currentCustomer: (entry as any).currentCustomer || '',
    nrIdentificacao: entry.nrIdentificacao || '',
    cdRcsHumano: (entry as any).cdRcsHumano || '',
    cpm: entry.cpm || (() => {
      const mins = entry.totalWorkingTimeMs / 60000;
      return mins > 0 ? Math.round((entry.totalPunnets / mins) * 100) / 100 : 0;
    })(),
    productionEntries: entry.productionEntries.map(p => ({
      'Registered at': p.timeRange,
      'Article name': p.articleName,
      'Device name': p.deviceName || entry.device,
      'Users': entry.user,
      'Customer': (p as any).customerName || '',
      'Net weight [kg]': p.netWeight,
      'Tare [kg]': 0,
      'Type': `${p.punnets} cestas | avg ${p.avgWeight.toFixed(3)}kg`,
      _registeredAt: p.registeredAt,
      _cpm: p.cpm,
      _punnets: p.punnets,
      _avgWeight: p.avgWeight,
      _timeRange: p.timeRange,
    })),
    sessionEntries: entry.sessionEntries.map(s => ({
      'User': entry.user,
      'Line': s.line || '',
      'Device': s.device || entry.device,
      'Activity': s.activity,
      'Working time': s.workingTime,
      'Login time': s.loginTime,
      'Logout time': s.logoutTime,
    })),
  });

  const liveDataAsGrouped: GroupedData[] = liveData.map(toGroupedData);
  const historyDataAsGrouped: GroupedData[] = historyData.map(toGroupedData);

  const sortedResults = getSortedResults();
  const activeResults = mode === 'live' ? liveDataAsGrouped : historyDataAsGrouped;

  const exportToExcel = (articleLabel?: string) => {
    const currentProcesso = mode === 'history' ? historyProcesso : processoBanner;
    const currentLoja = mode === 'history' ? historyLoja : lojaBanner;

    // Use historyData directly when in history mode
    const dataSource = mode === 'history' ? historyData : liveData;
    const data = dataSource.map(item => {
      const punnets = item.totalPunnets;
      const workingMinutes = item.totalWorkingTimeMs / 60000;
      const cpm = workingMinutes > 0 ? punnets / workingMinutes : 0;
      return {
        'Embaladora': item.user,
        'CdRcsHumano': (item as any).cdRcsHumano || '-',
        'Crachá': item.nrIdentificacao || '-',
        'Bloqueios': item.bloqueios || 0,
        'Balança': item.device,
        'Cestas': punnets,
        'Peso Total (kg)': Number(item.totalWeight.toFixed(3)),
        'CPM': Number(cpm.toFixed(2)),
        'Tempo Total': formatMsToDuration(item.totalWorkingTimeMs),
        'Qtd. Sessões': item.totalSessions,
      };
    }).sort((a, b) => b['Cestas'] - a['Cestas']);

    // Add a summary row
    const totalWeight = dataSource.reduce((acc, curr) => acc + curr.totalWeight, 0);
    const totalTimeMs = dataSource.reduce((acc, curr) => acc + curr.totalWorkingTimeMs, 0);
    const totalSessions = dataSource.reduce((acc, curr) => acc + curr.totalSessions, 0);
    const totalPunnets = dataSource.reduce((acc, curr) => acc + curr.totalPunnets, 0);
    const totalWorkingMin = totalTimeMs / 60000;
    const totalCpm = totalWorkingMin > 0 ? totalPunnets / totalWorkingMin : 0;

    data.push({
      'Embaladora': 'TOTAL GERAL',
      'CdRcsHumano': '-',
      'Crachá': '-',
      'Bloqueios': dataSource.reduce((acc, curr) => acc + (curr.bloqueios || 0), 0),
      'Balança': '-',
      'Cestas': totalPunnets,
      'Peso Total (kg)': Number(totalWeight.toFixed(3)),
      'CPM': Number(totalCpm.toFixed(2)),
      'Tempo Total': formatMsToDuration(totalTimeMs),
      'Qtd. Sessões': totalSessions,
    });

    // Add processo/loja info rows at the top
    const headerRows: Record<string, string | number>[] = [];
    if (currentProcesso) headerRows.push({ 'Embaladora': 'Processo:', 'CdRcsHumano': currentProcesso, 'Crachá': '', 'Bloqueios': '' as any, 'Balança': '', 'Cestas': '' as any, 'Peso Total (kg)': '' as any, 'CPM': '' as any, 'Tempo Total': '', 'Qtd. Sessões': '' as any });
    if (currentLoja) headerRows.push({ 'Embaladora': 'Loja:', 'CdRcsHumano': currentLoja, 'Crachá': '', 'Bloqueios': '' as any, 'Balança': '', 'Cestas': '' as any, 'Peso Total (kg)': '' as any, 'CPM': '' as any, 'Tempo Total': '', 'Qtd. Sessões': '' as any });
    if (headerRows.length > 0) headerRows.push({ 'Embaladora': '', 'CdRcsHumano': '', 'Crachá': '', 'Bloqueios': '' as any, 'Balança': '', 'Cestas': '' as any, 'Peso Total (kg)': '' as any, 'CPM': '' as any, 'Tempo Total': '', 'Qtd. Sessões': '' as any });

    const ws = XLSX.utils.json_to_sheet([...headerRows, ...data]);
    
    // Set column widths
    ws['!cols'] = [
      { wch: 30 }, // Embaladora
      { wch: 12 }, // CdRcsHumano
      { wch: 10 }, // Crachá
      { wch: 10 }, // Bloqueios
      { wch: 15 }, // Balança
      { wch: 15 }, // Cestas
      { wch: 18 }, // Peso Total
      { wch: 10 }, // CPM
      { wch: 15 }, // Tempo Total
      { wch: 15 }, // Qtd. Sessões
    ];

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Consolidado");

    // Gráfico sheet - ranking by cestas
    const sortedByCestasExport = [...dataSource].sort((a, b) => b.totalPunnets - a.totalPunnets);
    const totalOpsExport = sortedByCestasExport.length;
    const greenLimitExport = Math.ceil(totalOpsExport / 3);
    const yellowLimitExport = Math.ceil((totalOpsExport * 2) / 3);
    const graficoData = sortedByCestasExport.map((item, idx) => {
      const workingMin = item.totalWorkingTimeMs / 60000;
      const cpm = workingMin > 0 ? item.totalPunnets / workingMin : 0;
      const faixa = idx < greenLimitExport ? 'Verde' : idx < yellowLimitExport ? 'Amarelo' : 'Vermelho';
      return {
        'Posição': idx + 1,
        'Embaladora': item.user,
        'CdRcsHumano': item.cdRcsHumano || '-',
        'Crachá': item.nrIdentificacao || '-',
        'Bloqueios': item.bloqueios || 0,
        'Balança': item.device,
        'Cestas': item.totalPunnets,
        'Peso Total (kg)': Number(item.totalWeight.toFixed(3)),
        'CPM': Number(cpm.toFixed(2)),
        'Tempo Total': formatMsToDuration(item.totalWorkingTimeMs),
        'Faixa': faixa,
      };
    });
    const wsGrafico = XLSX.utils.json_to_sheet(graficoData);
    wsGrafico['!cols'] = [
      { wch: 8 }, { wch: 30 }, { wch: 12 }, { wch: 10 }, { wch: 10 },
      { wch: 15 }, { wch: 10 }, { wch: 18 }, { wch: 10 }, { wch: 15 }, { wch: 12 },
    ];
    XLSX.utils.book_append_sheet(wb, wsGrafico, "Gráfico");

    // Registros sheet - per-cesta detail
    const registrosData: Record<string, string | number>[] = [];
    sortedByCestasExport.forEach(entry => {
      entry.productionEntries.forEach(p => {
        const slotBase = p.registeredAt ? new Date(p.registeredAt) : null;
        const slotMinPerCesta = p.punnets > 0 ? 60 / p.punnets : 0;
        const qtfStr = formatMsToDuration(slotMinPerCesta * 60000);
        for (let c = 0; c < p.punnets; c++) {
          let timeStr = p.timeRange || '-';
          if (slotBase) {
            const cestaTime = new Date(slotBase.getTime() + c * slotMinPerCesta * 60000);
            timeStr = cestaTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          }
          registrosData.push({
            'Embaladora': entry.user,
            'CdRcsHumano': entry.cdRcsHumano || '-',
            'Crachá': entry.nrIdentificacao || '-',
            'Balança': entry.device,
            'Artigo': p.articleName,
            'Peso (kg)': Number(p.avgWeight.toFixed(3)),
            'Horário': timeStr,
            'QTF': qtfStr,
          });
        }
      });
    });
    const wsRegistros = XLSX.utils.json_to_sheet(registrosData);
    wsRegistros['!cols'] = [
      { wch: 30 }, { wch: 12 }, { wch: 10 }, { wch: 15 },
      { wch: 30 }, { wch: 12 }, { wch: 12 }, { wch: 12 },
    ];
    XLSX.utils.book_append_sheet(wb, wsRegistros, "Registros");
    
    const dateStr = new Date().toISOString().split('T')[0];
    const timeStr = new Date().toTimeString().split(' ')[0].replace(/:/g, '');
    const suffix = articleLabel ? `_${articleLabel.replace(/[^a-zA-Z0-9]/g, '_')}` : '';
    XLSX.writeFile(wb, `relatorio_consolidado_${dateStr}_${timeStr}${suffix}.xlsx`);
  };

  const exportArticleToExcel = (articleName: string) => {
    // Build per-user data for this specific article
    const dataSource = mode === 'history' ? historyData : liveData;
    const userData: Record<string, { user: string; weight: number; punnets: number; bloqueios: number; device: string; totalWorkingTimeMs: number; sessions: number; customers: string[]; nrIdentificacao: string; cdRcsHumano: string }> = {};
    dataSource.forEach(entry => {
      const operatorKey = getOperatorIdentityKey(entry);
      entry.productionEntries.forEach(p => {
        if (p.articleName !== articleName) return;
        if (!userData[operatorKey]) userData[operatorKey] = { user: entry.user, weight: 0, punnets: 0, bloqueios: entry.bloqueios || 0, device: entry.device, totalWorkingTimeMs: entry.totalWorkingTimeMs, sessions: entry.totalSessions, customers: (entry as any).customers || [], nrIdentificacao: entry.nrIdentificacao || '', cdRcsHumano: (entry as any).cdRcsHumano || '' };
        userData[operatorKey].weight += p.netWeight;
        userData[operatorKey].punnets += p.punnets;
      });
    });

    const rows = Object.entries(userData)
      .sort((a, b) => b[1].punnets - a[1].punnets)
      .map(([, d]) => {
        const workingMin = d.totalWorkingTimeMs / 60000;
        const cpm = workingMin > 0 ? d.punnets / workingMin : 0;
        return {
          'Embaladora': d.user,
          'CdRcsHumano': d.cdRcsHumano || '-',
          'Crach\u00e1': d.nrIdentificacao || '-',
          'Bloqueios': d.bloqueios || 0,
          'Balan\u00e7a': d.device,
          'Cestas': d.punnets,
          'Peso Total (kg)': Number(d.weight.toFixed(3)),
          'CPM': Number(cpm.toFixed(2)),
          'Tempo Total': formatMsToDuration(d.totalWorkingTimeMs),
          'Qtd. Sess\u00f5es': d.sessions,
        };
      });

    const totalWeight = rows.reduce((s, r) => s + r['Peso Total (kg)'], 0);
    const totalSessions = rows.reduce((s, r) => s + r['Qtd. Sess\u00f5es'], 0);
    const totalPunnets = rows.reduce((s, r) => s + r['Cestas'], 0);
    const totalTimeMs = Object.values(userData).reduce((s, d) => s + d.totalWorkingTimeMs, 0);
    const totalWorkingMin = totalTimeMs / 60000;
    const totalCpm = totalWorkingMin > 0 ? totalPunnets / totalWorkingMin : 0;

    rows.push({
      'Embaladora': 'TOTAL GERAL',
      'CdRcsHumano': '-',
      'Crach\u00e1': '-',
      'Bloqueios': Object.values(userData).reduce((s, d) => s + (d.bloqueios || 0), 0),
      'Balan\u00e7a': '-',
      'Cestas': totalPunnets,
      'Peso Total (kg)': Number(totalWeight.toFixed(3)),
      'CPM': Number(totalCpm.toFixed(2)),
      'Tempo Total': formatMsToDuration(totalTimeMs),
      'Qtd. Sess\u00f5es': totalSessions,
    });

    const ws = XLSX.utils.json_to_sheet(rows);
    ws['!cols'] = [
      { wch: 30 },
      { wch: 12 },
      { wch: 10 },
      { wch: 10 },
      { wch: 15 },
      { wch: 15 },
      { wch: 18 },
      { wch: 10 },
      { wch: 15 },
      { wch: 15 },
    ];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Consolidado');

    // Gráfico sheet - ranking for this article
    const sortedUsersExport = Object.entries(userData).sort((a, b) => b[1].punnets - a[1].punnets);
    const totalUsersExport = sortedUsersExport.length;
    const greenLimitArt = Math.ceil(totalUsersExport / 3);
    const yellowLimitArt = Math.ceil((totalUsersExport * 2) / 3);
    const graficoRows = sortedUsersExport.map(([, d], idx) => {
      const workingMin = d.totalWorkingTimeMs / 60000;
      const cpm = workingMin > 0 ? d.punnets / workingMin : 0;
      return {
        'Posição': idx + 1,
        'Embaladora': d.user,
        'CdRcsHumano': d.cdRcsHumano || '-',
        'Crachá': d.nrIdentificacao || '-',
        'Bloqueios': d.bloqueios || 0,
        'Balança': d.device,
        'Cestas': d.punnets,
        'Peso Total (kg)': Number(d.weight.toFixed(3)),
        'CPM': Number(cpm.toFixed(2)),
        'Faixa': idx < greenLimitArt ? 'Verde' : idx < yellowLimitArt ? 'Amarelo' : 'Vermelho',
      };
    });
    const wsGrafico = XLSX.utils.json_to_sheet(graficoRows);
    wsGrafico['!cols'] = [
      { wch: 8 }, { wch: 30 }, { wch: 12 }, { wch: 10 }, { wch: 10 },
      { wch: 15 }, { wch: 10 }, { wch: 18 }, { wch: 10 }, { wch: 12 },
    ];
    XLSX.utils.book_append_sheet(wb, wsGrafico, 'Gráfico');

    // Registros sheet - per-cesta detail for this article
    const regRows: Record<string, string | number>[] = [];
    sortedUsersExport.forEach(([operatorKey, d]) => {
      const entry = dataSource.find(e => getOperatorIdentityKey(e) === operatorKey);
      if (!entry) return;
      entry.productionEntries.filter(p => p.articleName === articleName).forEach(p => {
        const slotBase = p.registeredAt ? new Date(p.registeredAt) : null;
        const slotMinPerCesta = p.punnets > 0 ? 60 / p.punnets : 0;
        const qtfStr = formatMsToDuration(slotMinPerCesta * 60000);
        for (let c = 0; c < p.punnets; c++) {
          let timeStr = p.timeRange || '-';
          if (slotBase) {
            const cestaTime = new Date(slotBase.getTime() + c * slotMinPerCesta * 60000);
            timeStr = cestaTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
          }
          regRows.push({
            'Embaladora': d.user,
            'CdRcsHumano': d.cdRcsHumano || '-',
            'Crachá': d.nrIdentificacao || '-',
            'Balança': d.device,
            'Artigo': p.articleName,
            'Peso (kg)': Number(p.avgWeight.toFixed(3)),
            'Horário': timeStr,
            'QTF': qtfStr,
          });
        }
      });
    });
    const wsRegistros = XLSX.utils.json_to_sheet(regRows);
    wsRegistros['!cols'] = [
      { wch: 30 }, { wch: 12 }, { wch: 10 }, { wch: 15 },
      { wch: 30 }, { wch: 12 }, { wch: 12 }, { wch: 12 },
    ];
    XLSX.utils.book_append_sheet(wb, wsRegistros, 'Registros');

    const dateStr = new Date().toISOString().split('T')[0];
    const timeStr = new Date().toTimeString().split(' ')[0].replace(/:/g, '');
    const safeName = articleName.replace(/[^a-zA-Z0-9]/g, '_');
    XLSX.writeFile(wb, `relatorio_${safeName}_${dateStr}_${timeStr}.xlsx`);
    setShowExportMenu(false);
  };

  // Auto-export when articles change in live mode
  useEffect(() => {
    if (mode !== 'live' || liveData.length === 0) return;

    const currentArticles = [...new Set(liveData.flatMap(e => e.articles))].sort().join(',');
    const prev = prevArticlesRef.current;

    if (prev !== null && prev !== '' && currentArticles !== prev && !exportTriggeredRef.current) {
      console.log(`[AUTO-EXPORT] Artigo mudou: "${prev}" → "${currentArticles}"`);
      exportTriggeredRef.current = true;
      // Small timeout to let state settle
      setTimeout(() => {
        exportToExcel(prev);
        exportTriggeredRef.current = false;
      }, 500);
    }

    prevArticlesRef.current = currentArticles;
  }, [liveData, mode]);

  const hasResults = mode === 'live' ? liveData.length > 0 : mode === 'history' ? historyData.length > 0 : groupedResults.length > 0;
  const resultCount = mode === 'live' ? liveData.length : mode === 'history' ? historyData.length : groupedResults.length;

  return (
    <div className="min-h-screen bg-[#F8F9FA] text-[#1A1A1A] font-sans p-3 sm:p-6 md:p-12">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <header className="mb-6 md:mb-12 flex flex-col md:flex-row md:items-end justify-between gap-4 md:gap-6">
          <div>
            <img src="/logo.png" alt="Logo" className="h-14 object-contain" />
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            {/* Mode Toggle */}
            <div className="flex bg-white rounded-xl border border-gray-200 p-1 shadow-sm">
              <button
                onClick={() => setMode('live')}
                className={cn(
                  "flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all",
                  mode === 'live' ? "bg-emerald-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                )}
              >
                <Radio size={14} />
                Ao Vivo
              </button>
              <button
                onClick={() => setMode('history')}
                className={cn(
                  "flex items-center gap-2 px-3 sm:px-4 py-2 rounded-lg text-xs sm:text-sm font-semibold transition-all",
                  mode === 'history' ? "bg-violet-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                )}
              >
                <Package size={14} />
                Histórico
              </button>
            </div>
            {hasResults && (
              <div className="relative" ref={exportMenuRef}>
                <button
                  onClick={() => {
                    if (mode === 'history') {
                      setShowExportMenu(!showExportMenu);
                    } else {
                      exportToExcel();
                    }
                  }}
                  className="flex items-center gap-2 bg-[#1A1A1A] text-white px-4 sm:px-6 py-2.5 sm:py-3 rounded-xl hover:bg-[#333] transition-all shadow-sm text-xs sm:text-sm"
                >
                  <Download size={16} />
                  <span className="whitespace-nowrap">Exportar Excel</span>
                  {mode === 'history' && <ChevronDown size={14} />}
                </button>
                {showExportMenu && mode === 'history' && (
                  <div className="absolute right-0 top-full mt-2 bg-white rounded-xl border border-gray-200 shadow-lg z-50 w-[calc(100vw-2rem)] sm:w-auto sm:min-w-[420px] py-2 max-h-80 overflow-y-auto">
                    <button
                      onClick={() => { exportToExcel(); setShowExportMenu(false); }}
                      className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors text-sm font-semibold text-gray-800 border-b border-gray-100 flex items-center gap-2"
                    >
                      <Download size={14} />
                      Exportar Tudo
                    </button>
                    {(() => {
                      const exportSource = mode === 'history' ? historyData : liveData;
                      return [...new Set<string>(exportSource.flatMap(e => e.articles))].sort().map(art => {
                      let earliest = '';
                      let latest = '';
                      exportSource.forEach(e => e.productionEntries.forEach(p => {
                        if (p.articleName !== art) return;
                        if (!earliest || p.registeredAt < earliest) earliest = p.registeredAt;
                        if (!latest || p.registeredAt > latest) latest = p.registeredAt;
                      }));
                      const dateLabel = earliest ? new Date(earliest).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '';
                      const t1 = earliest ? new Date(earliest).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
                      const t2 = latest ? new Date(latest).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
                      return (
                        <button
                          key={art}
                          onClick={() => exportArticleToExcel(art)}
                          className="w-full text-left px-4 py-3 hover:bg-violet-50 transition-colors text-sm text-gray-700 flex items-center justify-between gap-3 group"
                        >
                          <div className="flex items-center gap-3">
                            <span className="bg-violet-100 text-violet-700 px-3 py-1 rounded-lg text-xs font-bold">{art}</span>
                          </div>
                          {dateLabel && (
                            <span className="text-[11px] text-gray-400 font-mono whitespace-nowrap">{dateLabel} · {t1} → {t2}</span>
                          )}
                        </button>
                      );
                    });
                    })()}
                  </div>
                )}
              </div>
            )}
          </div>
        </header>

        {/* Live Mode Status Bar */}
        {mode === 'live' && (
          <div className="mb-8 bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                {isLiveConnected ? (
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-3 w-3">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                    </span>
                    <Wifi size={16} className="text-emerald-500" />
                    <span className="text-sm font-medium text-emerald-700">
                      {(liveStats as any)?.source === 'gRPC' ? 'Conectado via gRPC' : 'Monitorando'}
                    </span>
                    {(liveStats as any)?.tokenStatus && (liveStats as any).tokenStatus !== 'valid' && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 font-medium">
                        Token: {(liveStats as any).tokenStatus}
                      </span>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <span className="relative flex h-3 w-3">
                      <span className="relative inline-flex rounded-full h-3 w-3 bg-red-500"></span>
                    </span>
                    <WifiOff size={16} className="text-red-500" />
                    <span className="text-sm font-medium text-red-600">Sem conexão com servidor</span>
                    <span className="text-xs text-gray-400 ml-1">(Execute: python server.py)</span>
                  </div>
                )}
              </div>
              {liveStats && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 sm:gap-6 text-xs text-gray-500 w-full sm:w-auto">
                  <div className="relative" ref={inactiveOpsRef}>
                    <button
                      onClick={() => setShowInactiveOps(v => !v)}
                      className="flex items-center gap-1 hover:bg-blue-50 px-2 py-1 rounded-lg transition-colors cursor-pointer"
                    >
                      <span className="font-semibold text-blue-600">{liveData.filter(e => e.sessionEntries.some(s => !s.logoutTime)).length}</span> operadores
                    </button>
                    {showInactiveOps && (() => {
                      const inactive = liveData.filter(e => !e.sessionEntries.some(s => !s.logoutTime));
                      return (
                        <div className="absolute top-full left-0 mt-2 z-50 bg-white border border-gray-200 rounded-xl shadow-lg p-4 min-w-[340px] max-h-[400px] overflow-y-auto">
                          <h3 className="text-sm font-bold text-gray-700 mb-3">Embaladoras inativas ({inactive.length})</h3>
                          {inactive.length === 0 ? (
                            <p className="text-xs text-gray-400">Todas as embaladoras estão ativas.</p>
                          ) : (
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="text-[10px] uppercase tracking-wider text-gray-400 border-b border-gray-100">
                                  <th className="pb-2 text-left">Embaladora</th>
                                  <th className="pb-2 text-left">CdRH</th>
                                  <th className="pb-2 text-left">Crachá</th>
                                  <th className="pb-2 text-left">Balança</th>
                                  <th className="pb-2 text-left">Entrada</th>
                                  <th className="pb-2 text-left">Saída</th>
                                </tr>
                              </thead>
                              <tbody>
                                {inactive.map((e, i) => {
                                  const lastSession = e.sessionEntries.length > 0 ? e.sessionEntries[e.sessionEntries.length - 1] : null;
                                  const loginStr = lastSession?.loginTime ? new Date(lastSession.loginTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-';
                                  const logoutStr = lastSession?.logoutTime ? new Date(lastSession.logoutTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '-';
                                  const devicesLabel = [...new Set(e.sessionEntries.map(s => s.device).filter(Boolean))].join(' / ') || lastSession?.device || e.device || '-';
                                  return (
                                    <tr key={i} className="border-b border-gray-50 last:border-0">
                                      <td className="py-1.5 font-medium text-gray-700">{e.user}</td>
                                      <td className="py-1.5"><span className="bg-cyan-50 text-cyan-700 px-1.5 py-0.5 rounded text-[10px] font-mono border border-cyan-100">{(e as any).cdRcsHumano || '-'}</span></td>
                                      <td className="py-1.5"><span className="bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded text-[10px] font-mono border border-indigo-100">{e.nrIdentificacao || '-'}</span></td>
                                      <td className="py-1.5"><span className="bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded text-[10px] font-mono">{devicesLabel}</span></td>
                                      <td className="py-1.5 text-gray-500">{loginStr}</td>
                                      <td className="py-1.5 text-red-500 font-medium">{logoutStr}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          )}
                        </div>
                      );
                    })()}
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-semibold text-violet-600">{(liveStats as any).punnetCount ?? '-'}</span> cestas
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-semibold text-emerald-600">{liveStats.sessionEntries}</span> sessões
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="font-semibold text-gray-700">{liveStats.groupedCount}</span> usuários
                  </div>
                  {liveStats.lastScan && (
                    <div className="flex items-center gap-1">
                      <RefreshCw size={12} className="animate-spin" style={{ animationDuration: '5s' }} />
                      Scan: {new Date(liveStats.lastScan * 1000).toLocaleTimeString()}
                    </div>
                  )}
                </div>
              )}
            </div>
            {liveStats && liveStats.filesFound && liveStats.filesFound.length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-2">
                {liveStats.filesFound.map((f: any, i: number) => (
                  <span key={i} className={cn(
                    "text-[11px] px-2 py-1 rounded-lg border font-medium",
                    f.type === 'production' ? "bg-blue-50 text-blue-700 border-blue-100" : "bg-emerald-50 text-emerald-700 border-emerald-100"
                  )}>
                    <FileText size={10} className="inline mr-1" />
                    {f.name} ({f.rows} linhas)
                  </span>
                ))}
              </div>
            )}
            {liveStats && (liveStats as any)?.source === 'gRPC' && (
              <div className="mt-3 pt-3 border-t border-gray-100 flex items-center gap-2 text-[11px] text-gray-500">
                <span className="px-2 py-1 rounded-lg border bg-violet-50 text-violet-700 border-violet-100 font-medium">
                  gRPC → 192.168.30.8:37270
                </span>
                <span className="px-2 py-1 rounded-lg border bg-blue-50 text-blue-700 border-blue-100 font-medium">
                  StatisticService + ReportService + TimeTrackingService
                </span>
              </div>
            )}
          </div>
        )}

        {/* Article History - History tab */}
        {mode === 'history' && (() => {
          const dataSource = historyData;
          // Build per-article data with per-user breakdown
          const articleMap: Record<string, { totalPunnets: number; totalWeight: number; users: Record<string, { user: string; punnets: number; weight: number; bloqueios: number; device: string; totalWorkingTimeMs: number; sessions: number; customers: string[]; currentCustomer: string; nrIdentificacao: string; cdRcsHumano: string; cpm: number; productionEntries: { articleName: string; timeRange: string; registeredAt: string; cpm?: number; punnets: number; netWeight: number; avgWeight: number }[]; sessionEntries: { activity: string; loginTime: string; logoutTime: string; workingTime: string; line: string; device: string }[] }>; firstSeen: string; lastSeen: string }> = {};
          dataSource.forEach(entry => {
            const operatorKey = getOperatorIdentityKey(entry);
            entry.productionEntries.forEach(p => {
              const art = p.articleName;
              if (!art) return;
              if (!articleMap[art]) {
                articleMap[art] = { totalPunnets: 0, totalWeight: 0, users: {}, firstSeen: p.registeredAt, lastSeen: p.registeredAt };
              }
              const a = articleMap[art];
              a.totalPunnets += p.punnets;
              a.totalWeight += p.netWeight;
              if (!a.users[operatorKey]) a.users[operatorKey] = { user: entry.user, punnets: 0, weight: 0, bloqueios: entry.bloqueios || 0, device: entry.device, totalWorkingTimeMs: entry.totalWorkingTimeMs, sessions: entry.totalSessions, customers: (entry as any).customers || [], currentCustomer: (entry as any).currentCustomer || '', nrIdentificacao: entry.nrIdentificacao || '', cdRcsHumano: (entry as any).cdRcsHumano || '', cpm: entry.cpm || (entry.totalWorkingTimeMs > 0 ? Math.round((entry.totalPunnets / (entry.totalWorkingTimeMs / 60000)) * 100) / 100 : 0), productionEntries: [], sessionEntries: entry.sessionEntries.map(s => ({ activity: s.activity, loginTime: s.loginTime, logoutTime: s.logoutTime, workingTime: s.workingTime, line: s.line, device: getSessionDeviceLabel(s, entry.device) })) };
              a.users[operatorKey].punnets += p.punnets;
              a.users[operatorKey].weight += p.netWeight;
              a.users[operatorKey].productionEntries.push({ articleName: p.articleName, timeRange: p.timeRange, registeredAt: p.registeredAt, cpm: p.cpm, punnets: p.punnets, netWeight: p.netWeight, avgWeight: p.avgWeight });
              if (p.registeredAt && (!a.firstSeen || p.registeredAt < a.firstSeen)) a.firstSeen = p.registeredAt;
              if (p.registeredAt && (!a.lastSeen || p.registeredAt > a.lastSeen)) a.lastSeen = p.registeredAt;
            });
          });
          const articles = Object.entries(articleMap).sort((a, b) => b[1].totalPunnets - a[1].totalPunnets);
          const grandTotalPunnets = articles.reduce((s, [, v]) => s + v.totalPunnets, 0);
          const grandTotalWeight = articles.reduce((s, [, v]) => s + v.totalWeight, 0);
          const grandTotalUsers = new Set(articles.flatMap(([, v]) => Object.keys(v.users))).size;

          const toggleArticle = (key: string) => {
            const next = new Set(expandedSlots);
            if (next.has(key)) next.delete(key); else next.add(key);
            setExpandedSlots(next);
          };

          return (
            <div className="space-y-4">
              {/* Summary bar with date picker */}
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <Package size={20} className="text-violet-500" />
                    <h2 className="text-xl font-bold">Histórico por Artigo</h2>
                    {/* Range mode toggle */}
                    <div className="flex ml-3 bg-gray-100 rounded-lg p-0.5">
                      {(['day', 'week', 'range'] as const).map(rm => (
                        <button
                          key={rm}
                          onClick={() => setHistoryRangeMode(rm)}
                          className={cn(
                            "px-3 py-1 text-xs font-semibold rounded-md transition-colors",
                            historyRangeMode === rm ? "bg-violet-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                          )}>
                          {rm === 'day' ? 'Dia' : rm === 'week' ? 'Semana' : 'Intervalo'}
                        </button>
                      ))}
                    </div>
                    {historyLoading && (
                      <RefreshCw size={16} className="animate-spin text-violet-400" />
                    )}
                  </div>
                  <div className="flex items-center gap-6 text-sm">
                    <span className="font-mono font-bold text-violet-600">{grandTotalPunnets} cestas</span>
                    <span className="font-mono font-bold text-blue-600">{grandTotalWeight.toFixed(3)} kg</span>
                    <span className="text-gray-500">{grandTotalUsers} operador{grandTotalUsers !== 1 ? 'es' : ''}</span>
                    <span className="text-gray-400">{articles.length} artigo{articles.length !== 1 ? 's' : ''}</span>
                  </div>
                </div>
                {/* Date controls */}
                <div className="flex flex-wrap items-center gap-3">
                  {historyRangeMode === 'day' && (
                    <input
                      type="date"
                      value={historyDate}
                      onChange={(e) => setHistoryDate(e.target.value)}
                      className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
                    />
                  )}
                  {historyRangeMode === 'week' && (() => {
                    const { start, end } = getWeekRange(historyDate);
                    const fmtDate = (s: string) => new Date(s + 'T12:00:00').toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                    return (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => { const d = new Date(historyDate + 'T12:00:00'); d.setDate(d.getDate() - 7); setHistoryDate(d.toISOString().split('T')[0]); }}
                          className="px-2 py-1 rounded-lg border border-gray-200 hover:bg-gray-50 text-sm"
                        >&larr;</button>
                        <span className="px-3 py-1.5 rounded-lg border border-violet-200 bg-violet-50 text-sm font-semibold text-violet-700">
                          {fmtDate(start)} &mdash; {fmtDate(end)}
                        </span>
                        <button
                          onClick={() => { const d = new Date(historyDate + 'T12:00:00'); d.setDate(d.getDate() + 7); setHistoryDate(d.toISOString().split('T')[0]); }}
                          className="px-2 py-1 rounded-lg border border-gray-200 hover:bg-gray-50 text-sm"
                        >&rarr;</button>
                        <input
                          type="date"
                          value={historyDate}
                          onChange={(e) => setHistoryDate(e.target.value)}
                          className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
                        />
                      </div>
                    );
                  })()}
                  {historyRangeMode === 'range' && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500 font-medium">De</span>
                      <input
                        type="date"
                        value={historyDate}
                        onChange={(e) => setHistoryDate(e.target.value)}
                        className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
                      />
                      <span className="text-xs text-gray-500 font-medium">até</span>
                      <input
                        type="date"
                        value={historyEndDate}
                        onChange={(e) => setHistoryEndDate(e.target.value)}
                        className="px-3 py-1.5 rounded-lg border border-gray-200 text-sm font-mono bg-gray-50 focus:outline-none focus:ring-2 focus:ring-violet-300 focus:border-violet-400"
                      />
                    </div>
                  )}
                  {historyRangeMode !== 'day' && historyDays.length > 0 && (
                    <span className="text-xs text-gray-400 ml-2">
                      {historyDays.filter(d => d.operatorCount > 0).length} dia{historyDays.filter(d => d.operatorCount > 0).length !== 1 ? 's' : ''} com dados
                    </span>
                  )}
                </div>
              </div>

              {/* Daily breakdown for range/week modes */}
              {historyRangeMode !== 'day' && historyDays.length > 0 && (
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                  <div className="px-5 py-3 border-b border-gray-100">
                    <h3 className="text-sm font-bold text-gray-700">Resumo Diário</h3>
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 text-[11px] uppercase tracking-wider text-gray-500">
                        <th className="px-4 py-2 text-left">Dia</th>
                        <th className="px-4 py-2 text-right">Cestas</th>
                        <th className="px-4 py-2 text-right">Peso (kg)</th>
                        <th className="px-4 py-2 text-right">Operadores</th>
                      </tr>
                    </thead>
                    <tbody>
                      {historyDays.map(day => {
                        const dayDate = new Date(day.date + 'T12:00:00');
                        const weekday = dayDate.toLocaleDateString('pt-BR', { weekday: 'short' });
                        const dateStr = dayDate.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
                        return (
                          <tr key={day.date} className={cn("border-t border-gray-50", day.operatorCount === 0 && "opacity-40")}>
                            <td className="px-4 py-2 font-medium">
                              <span className="text-gray-700">{dateStr}</span>
                              <span className="ml-2 text-gray-400 text-xs capitalize">{weekday}</span>
                            </td>
                            <td className="px-4 py-2 text-right font-mono font-bold text-violet-600">{day.totalPunnets}</td>
                            <td className="px-4 py-2 text-right font-mono text-blue-600">{day.totalWeight.toFixed(3)}</td>
                            <td className="px-4 py-2 text-right text-gray-500">{day.operatorCount}</td>
                          </tr>
                        );
                      })}
                      <tr className="border-t-2 border-gray-200 bg-gray-50 font-bold">
                        <td className="px-4 py-2">TOTAL</td>
                        <td className="px-4 py-2 text-right font-mono text-violet-700">{historyDays.reduce((s, d) => s + d.totalPunnets, 0)}</td>
                        <td className="px-4 py-2 text-right font-mono text-blue-700">{historyDays.reduce((s, d) => s + d.totalWeight, 0).toFixed(3)}</td>
                        <td className="px-4 py-2 text-right text-gray-600">{grandTotalUsers}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              )}

              {/* Empty state */}
              {!historyLoading && articles.length === 0 && (
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-12 text-center">
                  <Package size={48} className="text-gray-300 mx-auto mb-4" />
                  <p className="text-gray-500 text-lg font-medium">
                    {historyRangeMode === 'day'
                      ? `Nenhum dado encontrado para ${new Date(historyDate + 'T12:00:00').toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}`
                      : 'Nenhum dado encontrado para o período selecionado'}
                  </p>
                  <p className="text-gray-400 text-sm mt-2">Selecione outra data para visualizar o histórico</p>
                </div>
              )}

              {/* Processo & Loja Banner */}
              {(historyProcesso || historyLoja) && (
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-6 py-3 flex flex-wrap items-center gap-6">
                  {historyProcesso && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wider font-bold text-violet-400">Processo</span>
                      <span className="text-sm font-semibold text-violet-700 bg-violet-100 px-3 py-1 rounded-lg">{historyProcesso}</span>
                    </div>
                  )}
                  {historyLoja && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] uppercase tracking-wider font-bold text-amber-400">Loja</span>
                      <span className="text-sm font-semibold text-amber-700 bg-amber-100 px-3 py-1 rounded-lg">{historyLoja}</span>
                      {/* CPM geral ao lado da loja */}
                      {(() => {
                        // CPM geral: média dos CPMs dos operadores de todos os artigos
                        let allUsers = articles.flatMap(([, info]) => Object.values(info.users));
                        let allCpms = allUsers.map(u => u.cpm ?? 0).filter(c => typeof c === 'number' && !isNaN(c));
                        let avgCpm = allCpms.length > 0 ? (allCpms.reduce((a, b) => a + b, 0) / allCpms.length) : 0;
                        return (
                          <span className="ml-2 text-xs font-bold text-orange-700 bg-orange-50 px-2 py-0.5 rounded-full border border-orange-100">CPM Geral: {avgCpm.toFixed(2)}</span>
                        );
                      })()}
                    </div>
                  )}
                </div>
              )}

              {/* View Mode Toggle */}
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
                <div className="flex items-center gap-4">
                  <div className="flex bg-gray-100 rounded-lg p-0.5">
                    <button
                      onClick={() => setHistoryViewMode('geral')}
                      className={cn(
                        "px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5",
                        historyViewMode === 'geral' ? "bg-emerald-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                      )}>
                      <TableIcon size={12} /> Geral
                    </button>
                    <button
                      onClick={() => setHistoryViewMode('grafico')}
                      className={cn(
                        "px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5",
                        historyViewMode === 'grafico' ? "bg-blue-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                      )}>
                      <BarChart3 size={12} /> Gráfico
                    </button>
                    <button
                      onClick={() => setHistoryViewMode('registros')}
                      className={cn(
                        "px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5",
                        historyViewMode === 'registros' ? "bg-violet-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                      )}>
                      <List size={12} /> Registros
                    </button>
                  </div>
                </div>
              </div>

              {/* Article rows (Geral view) */}
              {historyViewMode === 'geral' && articles.map(([name, info]) => {
                const isOpen = expandedSlots.has(name);
                const firstTime = info.firstSeen ? new Date(info.firstSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '?';
                const lastTime = info.lastSeen ? new Date(info.lastSeen).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '?';
                const dateStr = info.firstSeen ? new Date(info.firstSeen).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : '';
                const userCount = Object.keys(info.users).length;
                const usersArr = Object.entries(info.users).sort((a, b) => {
                  if (!sortConfig) return b[1].punnets - a[1].punnets;
                  const field = sortConfig.field;
                  const dir = sortConfig.order === 'asc' ? 1 : -1;
                  if (field === 'user') return dir * a[1].user.localeCompare(b[1].user);
                  if (field === 'cdRcsHumano') return dir * ((a[1] as any).cdRcsHumano || '').localeCompare((b[1] as any).cdRcsHumano || '');
                  if (field === 'nrIdentificacao') return dir * ((a[1] as any).nrIdentificacao || '').localeCompare((b[1] as any).nrIdentificacao || '');
                  if (field === 'bloqueios') return dir * (((a[1] as any).bloqueios || 0) - ((b[1] as any).bloqueios || 0));
                  if (field === 'device') return dir * a[1].device.localeCompare(b[1].device);
                  if (field === 'punnets' || field === 'productionCount') return dir * (a[1].punnets - b[1].punnets);
                  if (field === 'totalWeight') return dir * (a[1].weight - b[1].weight);
                  if (field === 'cpm') return dir * (((a[1] as any).cpm || 0) - ((b[1] as any).cpm || 0));
                  if (field === 'totalWorkingTimeMs') return dir * (a[1].totalWorkingTimeMs - b[1].totalWorkingTimeMs);
                  if (field === 'totalSessions') return dir * (a[1].sessions - b[1].sessions);
                  return b[1].punnets - a[1].punnets;
                });

                return (
                  <div key={name} className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                    {/* Collapsible header row */}
                    <button
                      onClick={() => toggleArticle(name)}
                      className="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors text-left group"
                    >
                      <div className="flex items-center gap-4">
                        {isOpen ? <ChevronDown size={16} className="text-violet-500" /> : <ChevronRight size={16} className="text-gray-400 group-hover:text-violet-500" />}
                        <span className="bg-violet-100 text-violet-700 px-4 py-2 rounded-xl font-bold text-base">
                          {name}
                        </span>
                        <span className="text-sm text-gray-400">
                          {dateStr && <>{dateStr} · </>}{firstTime} → {lastTime}
                        </span>
                      </div>
                      <div className="flex items-center gap-6 text-sm">
                        <span className="font-mono font-bold text-violet-600">{info.totalPunnets} cestas</span>
                        <span className="font-mono font-bold text-blue-600">{info.totalWeight.toFixed(3)} kg</span>
                        <span className="text-gray-500">{userCount} operador{userCount !== 1 ? 'es' : ''}</span>
                      </div>
                    </button>

                    {/* Expanded user table */}
                    <AnimatePresence>
                      {isOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="overflow-hidden"
                        >
                          <div className="border-t border-gray-100">
                            <table className="w-full text-sm">
                              <thead className="bg-gray-50/80 text-[11px] uppercase tracking-wider text-gray-500 font-bold">
                                <tr>
                                  <th className="p-3 w-8"></th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('user')}>
                                    <div className="flex items-center gap-1">Embaladora {sortConfig?.field === 'user' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('cdRcsHumano')}>
                                    <div className="flex items-center gap-1">CdRH {sortConfig?.field === 'cdRcsHumano' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('nrIdentificacao')}>
                                    <div className="flex items-center gap-1">Crachá {sortConfig?.field === 'nrIdentificacao' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('bloqueios')}>
                                    <div className="flex items-center gap-1">Bloqueios {sortConfig?.field === 'bloqueios' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('device')}>
                                    <div className="flex items-center gap-1">Balança {sortConfig?.field === 'device' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('punnets')}>
                                    <div className="flex items-center gap-1">Cestas {sortConfig?.field === 'punnets' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('totalWeight')}>
                                    <div className="flex items-center gap-1">Peso Total (kg) {sortConfig?.field === 'totalWeight' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('cpm')}>
                                    <div className="flex items-center gap-1">CPM {sortConfig?.field === 'cpm' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('totalWorkingTimeMs')}>
                                    <div className="flex items-center gap-1">Tempo Total {sortConfig?.field === 'totalWorkingTimeMs' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                  <th className="p-3 text-left cursor-pointer hover:bg-gray-100" onClick={() => requestSort('totalSessions')}>
                                    <div className="flex items-center gap-1">Sessões {sortConfig?.field === 'totalSessions' ? (sortConfig.order === 'asc' ? <ArrowUp size={10} /> : <ArrowDown size={10} />) : <ArrowUpDown size={10} className="text-gray-300" />}</div>
                                  </th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-50">
                                {/* Colorir CPM por faixa fixa */}
                                {(() => {
                                  return usersArr.map(([operatorKey, data], idx) => {
                                  const userRowKey = `${name}|${operatorKey}`;
                                  const isUserOpen = expandedSlots.has(userRowKey);
                                  const cpmValue = (data as any).cpm ?? 0;
                                  const cpmStyles = getCpmStyles(cpmValue);
                                  const cpmColor = cpmStyles.badge;
                                  const cpmBorderLeft = cpmStyles.accent;
                                  return (
                                    <React.Fragment key={operatorKey}>
                                      <tr
                                        className={cn("hover:bg-gray-50/50 cursor-pointer group transition-colors", isUserOpen && "bg-blue-50/30")}
                                        onClick={() => toggleArticle(userRowKey)}
                                      >
                                        <td className="p-3 text-center">
                                          {isUserOpen ? <ChevronDown size={14} className="text-violet-500" /> : <ChevronRight size={14} className="text-gray-400 group-hover:text-violet-500" />}
                                        </td>
                                        <td className="p-3 font-medium text-gray-800">{data.user}</td>
                                        <td className="p-3">
                                          <span className="bg-cyan-50 text-cyan-700 px-2 py-1 rounded text-xs font-mono border border-cyan-100">{(data as any).cdRcsHumano || '-'}</span>
                                        </td>
                                        <td className="p-3">
                                          <span className="bg-indigo-50 text-indigo-700 px-2 py-1 rounded text-xs font-mono border border-indigo-100">{(data as any).nrIdentificacao || '-'}</span>
                                        </td>
                                        <td className="p-3">
                                          <span className="bg-amber-50 text-amber-700 px-2 py-1 rounded text-xs font-mono border border-amber-100">{(data as any).bloqueios || 0}</span>
                                        </td>
                                        <td className="p-3">
                                          <span className="bg-gray-100 px-2 py-1 rounded text-xs font-mono text-gray-600">{data.device}</span>
                                        </td>
                                        <td className="p-3">
                                          <span className="inline-flex items-center whitespace-nowrap bg-violet-50 text-violet-700 px-2 py-0.5 rounded-full text-xs font-medium border border-violet-100">{data.punnets} cestas</span>
                                        </td>
                                        <td className="p-3 font-mono text-blue-600 font-semibold">{data.weight.toFixed(3)}</td>
                                        <td className="p-3">
                                          <span className={cn("px-2 py-0.5 rounded-full text-xs font-bold border", cpmColor)}>{cpmValue.toFixed(2)}</span>
                                        </td>
                                        <td className="p-3 font-mono text-gray-600">{formatMsToDuration(data.totalWorkingTimeMs)}</td>
                                        <td className="p-3">
                                          <span className="bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full text-xs font-medium border border-emerald-100">{data.sessions}</span>
                                        </td>
                                      </tr>
                                      <AnimatePresence>
                                        {isUserOpen && (
                                          <tr>
                                            <td colSpan={11} className="p-0">
                                              <motion.div
                                                initial={{ height: 0, opacity: 0 }}
                                                animate={{ height: 'auto', opacity: 1 }}
                                                exit={{ height: 0, opacity: 0 }}
                                                className="overflow-hidden bg-gray-50/80 border-y border-gray-100"
                                              >
                                                <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
                                                  <div>
                                                    <h4 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                                      <LayoutGrid size={14} />
                                                      Produção por Hora ({data.productionEntries.length})
                                                    </h4>
                                                    <div className="max-h-60 overflow-y-auto space-y-2 pr-2 custom-scrollbar">
                                                      {data.productionEntries.map((p, i) => {
                                                        const productionCpm = getProductionEntryCpm(p, data.sessionEntries, cpmValue);
                                                        const productionCpmStyles = getCpmStyles(productionCpm);
                                                        return (
                                                        <div key={i} className={cn("bg-white p-3 rounded-lg border border-gray-100 text-sm", productionCpmStyles.accent)}>
                                                          <div className="flex justify-between items-start mb-1">
                                                            <p className="font-medium">{p.articleName}</p>
                                                            <p className="font-mono font-bold text-blue-600">{p.netWeight.toFixed(3)}kg</p>
                                                          </div>
                                                          <div className="flex items-center gap-3 text-xs text-gray-500">
                                                            <span className={cn("font-mono px-1.5 py-0.5 rounded", productionCpmStyles.badge)}>{getProductionTimeLabel(p)}</span>
                                                            <span className="text-violet-600 font-semibold">{p.punnets} cestas</span>
                                                            <span>avg {p.avgWeight.toFixed(3)}kg</span>
                                                            <span className={cn("px-1.5 py-0.5 rounded-full font-bold border", productionCpmStyles.badge)}>CPM {productionCpm.toFixed(2)}</span>
                                                          </div>
                                                        </div>
                                                      );})}
                                                    </div>
                                                  </div>
                                                  <div>
                                                    <h4 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                                      <TableIcon size={14} />
                                                      Sessões de Trabalho ({data.sessionEntries.length})
                                                    </h4>
                                                    <div className="max-h-60 overflow-y-auto space-y-2 pr-2 custom-scrollbar">
                                                      {data.sessionEntries.map((s, i) => {
                                                        const loginStr = s.loginTime ? new Date(s.loginTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
                                                        const logoutStr = s.logoutTime ? new Date(s.logoutTime).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'ativa';
                                                        const timeDisplay = loginStr ? `${loginStr} → ${logoutStr}` : '';
                                                        const deviceLabel = getSessionDeviceLabel(s, data.device);
                                                        return (
                                                          <div key={i} className="bg-white p-3 rounded-lg border border-gray-100 text-sm">
                                                            <div className="flex justify-between items-start mb-1">
                                                              <div>
                                                                <p className="font-medium">{s.activity || 'Sessão'}</p>
                                                                {s.line && <p className="text-[10px] text-gray-400">{s.line}</p>}
                                                                {deviceLabel && <p className="text-[10px] text-gray-400">Balança {deviceLabel}</p>}
                                                              </div>
                                                              <p className="font-mono text-emerald-600 font-semibold">{s.workingTime}</p>
                                                            </div>
                                                            {timeDisplay && (
                                                              <p className="text-xs text-gray-500 font-mono bg-gray-50 px-2 py-0.5 rounded inline-block">
                                                                {timeDisplay}
                                                              </p>
                                                            )}
                                                          </div>
                                                        );
                                                      })}
                                                    </div>
                                                  </div>
                                                </div>
                                              </motion.div>
                                            </td>
                                          </tr>
                                        )}
                                      </AnimatePresence>
                                    </React.Fragment>
                                  );
                                });
                                })()}
                              </tbody>
                            </table>
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                );
              })}

              {/* History Gráfico View */}
              {historyViewMode === 'grafico' && (() => {
                const sortedByCestas = [...historyData].sort((a, b) => b.totalPunnets - a.totalPunnets);
                const totalOps = historyData.length;
                const greenLimit = Math.ceil(totalOps / 3);
                const yellowLimit = Math.ceil((totalOps * 2) / 3);
                const getColor = (rank: number) => {
                  if (rank < greenLimit) return { bar: 'bg-emerald-500', text: 'text-emerald-700', dot: 'bg-emerald-400' };
                  if (rank < yellowLimit) return { bar: 'bg-yellow-500', text: 'text-yellow-700', dot: 'bg-yellow-400' };
                  return { bar: 'bg-red-500', text: 'text-red-700', dot: 'bg-red-400' };
                };
                const getCestasRank = (entry: typeof historyData[0]) => sortedByCestas.findIndex(e => getOperatorIdentityKey(e) === getOperatorIdentityKey(entry));
                const filtered = chartSelectedOps.size > 0 ? sortedByCestas.filter(e => chartSelectedOps.has(getOperatorIdentityKey(e))) : sortedByCestas;
                const maxPunnets = Math.max(...(chartSelectedOps.size > 0 ? filtered : sortedByCestas).map(e => e.totalPunnets), 1);
                const chartH = chartFullscreen ? 600 : 400;
                const gridSteps = 5;
                const gridLines = Array.from({ length: gridSteps + 1 }, (_, i) => Math.round((maxPunnets / gridSteps) * (gridSteps - i)));
                const toggleChartOp = (key: string) => { const next = new Set(chartSelectedOps); if (next.has(key)) next.delete(key); else next.add(key); setChartSelectedOps(next); };
                const barW = filtered.length <= 8 ? 72 : filtered.length <= 15 ? 50 : 34;
                const totalChartW = Math.max(filtered.length * (barW + 4) + 44, 400);

                return (
                  <motion.div layout transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
                    className={cn("flex bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden", chartFullscreen ? "fixed inset-0 z-50 bg-white shadow-2xl rounded-none" : "")}
                    style={{ minHeight: chartFullscreen ? '100vh' : '550px' }}>
                    <div className={cn("w-[20%] border-r border-gray-100 overflow-y-auto", chartFullscreen ? "h-screen" : "")} style={chartFullscreen ? {} : { maxHeight: '600px' }}>
                      <div className="p-3">
                        <button onClick={() => setChartFullscreen(!chartFullscreen)} className="w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all mb-2 bg-gray-100 text-gray-600 hover:bg-gray-200">
                          {chartFullscreen ? '✕ Fechar Tela Cheia' : '⛶ Tela Cheia'}
                        </button>
                        <button onClick={() => setChartSelectedOps(new Set())} className={cn("w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition-all mb-1", chartSelectedOps.size === 0 ? "bg-blue-500 text-white shadow-sm" : "text-gray-600 hover:bg-gray-50")}>
                          Todas
                        </button>
                        {sortedByCestas.map((entry, idx) => {
                          const colors = getColor(idx);
                          const opKey = getOperatorIdentityKey(entry);
                          const isSelected = chartSelectedOps.has(opKey);
                          return (
                            <button key={opKey} onClick={() => toggleChartOp(opKey)}
                              className={cn("w-full text-left px-3 py-2 rounded-lg text-sm transition-all mb-0.5 flex items-center gap-2", isSelected ? "bg-blue-50 text-blue-700 font-semibold ring-1 ring-blue-200" : "text-gray-600 hover:bg-gray-50")}>
                              <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", colors.dot)} />
                              <div className="flex flex-col min-w-0">
                                <span className="truncate">{entry.user}</span>
                                <div className="flex gap-1.5 text-[9px] font-mono text-gray-400">
                                  <span>{entry.cdRcsHumano || '-'}</span><span>·</span><span>{entry.nrIdentificacao || '-'}</span>
                                </div>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <motion.div layout className="w-[80%] p-6 overflow-x-auto overflow-y-hidden">
                      <div className="relative" style={{ height: chartH + 80, minWidth: totalChartW }}>
                        {gridLines.map((val, i) => {
                          const top = (i / gridSteps) * chartH;
                          return (
                            <div key={i} className="absolute w-full flex items-center" style={{ top, left: 0, right: 0 }}>
                              <span className="text-[10px] text-gray-400 font-mono w-10 text-right pr-2 shrink-0">{val}</span>
                              <div className="flex-1 border-t border-gray-200" />
                            </div>
                          );
                        })}
                        <div className="absolute flex gap-1 items-end" style={{ left: 44, right: 0, bottom: 0, height: chartH + 80 }}>
                          {filtered.map((entry) => {
                            const cestasRank = getCestasRank(entry);
                            const barHeightPx = Math.max(Math.round((entry.totalPunnets / maxPunnets) * chartH), 4);
                            const colors = getColor(cestasRank);
                            return (
                                <motion.div key={getOperatorIdentityKey(entry)} layout transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
                                className="flex flex-col items-center justify-end" style={{ width: barW, minWidth: barW, flexShrink: 0 }}>
                                <motion.span layout className="text-[10px] font-bold text-gray-600 mb-1 whitespace-nowrap">{entry.totalPunnets}</motion.span>
                                <motion.div layout animate={{ height: barHeightPx }} transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
                                  className={cn("w-full rounded-t-md shadow-sm", colors.bar)}
                                  title={`${entry.user}\nCestas: ${entry.totalPunnets}\nPeso: ${entry.totalWeight.toFixed(3)} kg`} />
                                <div className="h-16 flex items-start justify-center pt-1 overflow-hidden" style={{ width: '100%' }}>
                                  <span className={cn("text-[9px] font-semibold", colors.text)}
                                    style={{ writingMode: 'vertical-rl', textOrientation: 'mixed', maxHeight: 58, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {entry.user}
                                  </span>
                                </div>
                              </motion.div>
                            );
                          })}
                        </div>
                      </div>
                    </motion.div>
                  </motion.div>
                );
              })()}

              {/* History Registros View - List layout */}
              {historyViewMode === 'registros' && (() => {
                const sorted = [...historyData].sort((a, b) => b.totalPunnets - a.totalPunnets);
                const totalOpsR = sorted.length;
                const greenLimitR = Math.ceil(totalOpsR / 3);
                const yellowLimitR = Math.ceil((totalOpsR * 2) / 3);
                const getColorR = (rank: number) => {
                  if (rank < greenLimitR) return { dot: 'bg-emerald-400', badge: 'bg-emerald-50 text-emerald-700 border-emerald-100' };
                  if (rank < yellowLimitR) return { dot: 'bg-yellow-400', badge: 'bg-yellow-50 text-yellow-700 border-yellow-100' };
                  return { dot: 'bg-red-400', badge: 'bg-red-50 text-red-700 border-red-100' };
                };
                const selectedRegOp = registrosExpandedOps.size > 0 ? [...registrosExpandedOps][0] : null;
                const selectedEntry = selectedRegOp ? sorted.find(e => getOperatorIdentityKey(e) === selectedRegOp) : null;
                const toggleOp = (key: string) => { setRegistrosExpandedOps(new Set(registrosExpandedOps.has(key) ? [] : [key])); };

                return (
                  <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden flex" style={{ minHeight: 550 }}>
                    <div className="w-[25%] border-r border-gray-100 overflow-y-auto" style={{ maxHeight: 650 }}>
                      <div className="p-3">
                        {sorted.map((entry, idx) => {
                          const colors = getColorR(idx);
                          const opKey = getOperatorIdentityKey(entry);
                          const isSelected = opKey === selectedRegOp;
                          const cpm = entry.cpm || (entry.totalWorkingTimeMs > 0 ? entry.totalPunnets / (entry.totalWorkingTimeMs / 60000) : 0);
                          const cpmStyles = getCpmStyles(cpm);
                          return (
                            <button key={opKey} onClick={() => toggleOp(opKey)}
                              className={cn("w-full text-left px-3 py-2.5 rounded-lg text-sm transition-all mb-0.5", isSelected ? "bg-blue-50 ring-1 ring-blue-200 shadow-sm" : "hover:bg-gray-50")}>
                              <div className="flex items-center gap-2">
                                <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", colors.dot)} />
                                <span className={cn("font-semibold truncate", isSelected ? "text-blue-700" : "text-gray-700")}>{entry.user}</span>
                              </div>
                              <div className="flex items-center gap-2 mt-1 ml-4.5 text-[10px] text-gray-400 font-mono">
                                <span>{entry.cdRcsHumano || '-'}</span><span>·</span><span>{entry.nrIdentificacao || '-'}</span><span>·</span><span>{entry.device}</span>
                              </div>
                              <div className="flex items-center gap-3 mt-1 ml-4.5 text-[10px]">
                                <span className="font-bold text-violet-600">{entry.totalPunnets} cestas</span>
                                <span className="font-bold text-blue-600">{entry.totalWeight.toFixed(1)} kg</span>
                                <span className={cn("px-1.5 py-0.5 rounded-full font-bold border text-[9px]", cpmStyles.badge)}>CPM {cpm.toFixed(2)}</span>
                              </div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                    <div className="w-[75%] p-4 overflow-y-auto" style={{ maxHeight: 650 }}>
                      {!selectedEntry ? (
                        <div className="flex items-center justify-center h-full text-gray-400">
                          <div className="text-center">
                            <List size={48} className="mx-auto mb-4 text-gray-300" />
                            <p className="text-lg font-medium">Selecione um operador</p>
                            <p className="text-sm mt-1">Clique em um nome à esquerda para ver os registros individuais</p>
                          </div>
                        </div>
                      ) : (() => {
                        const entry = selectedEntry;
                        const cestasRank = sorted.findIndex(e => getOperatorIdentityKey(e) === getOperatorIdentityKey(entry));
                        const colors = getColorR(cestasRank);
                        const cpm = entry.cpm || (entry.totalWorkingTimeMs > 0 ? entry.totalPunnets / (entry.totalWorkingTimeMs / 60000) : 0);
                        const cpmStyles = getCpmStyles(cpm);
                        const allCestas: { articleName: string; weight: number; time: string; qtf: string }[] = [];
                        entry.productionEntries.forEach(p => {
                          const slotBase = p.registeredAt ? new Date(p.registeredAt) : null;
                          const slotMinutesPerCesta = p.punnets > 0 ? 60 / p.punnets : 0;
                          const qtfStr = formatMsToDuration(slotMinutesPerCesta * 60000);
                          for (let c = 0; c < p.punnets; c++) {
                            let timeStr = p.timeRange || '-';
                            if (slotBase) {
                              const cestaTime = new Date(slotBase.getTime() + c * slotMinutesPerCesta * 60000);
                              timeStr = cestaTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                            }
                            allCestas.push({ articleName: p.articleName, weight: p.avgWeight, time: timeStr, qtf: qtfStr });
                          }
                        });
                        const key = getOperatorIdentityKey(entry);
                        const visibleCount = registrosVisibleCounts[key] || 80;
                        const visibleCestas = allCestas.slice(0, visibleCount);
                        const hasMore = allCestas.length > visibleCount;
                        return (
                          <div>
                            <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
                              <div className="flex items-center gap-3">
                                <span className={cn("w-3 h-3 rounded-full", colors.dot)} />
                                <span className="font-bold text-lg text-gray-800">{entry.user}</span>
                                <span className="bg-cyan-50 text-cyan-700 px-2 py-0.5 rounded text-xs font-mono border border-cyan-100">{entry.cdRcsHumano || '-'}</span>
                                <span className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-mono border border-indigo-100">{entry.nrIdentificacao || '-'}</span>
                                <span className="bg-gray-100 px-2 py-0.5 rounded text-xs font-mono text-gray-500">{entry.device}</span>
                              </div>
                              <div className="flex items-center gap-4 text-sm">
                                <span className="font-mono font-bold text-violet-600">{entry.totalPunnets} cestas</span>
                                <span className="font-mono font-bold text-blue-600">{entry.totalWeight.toFixed(3)} kg</span>
                                <span className={cn("px-2 py-0.5 rounded-full font-bold border text-xs", cpmStyles.badge)}>CPM {cpm.toFixed(2)}</span>
                                <span className="text-gray-400 font-mono text-xs">{formatMsToDuration(entry.totalWorkingTimeMs)}</span>
                              </div>
                            </div>
                            <table className="w-full text-sm">
                              <thead className="sticky top-0 bg-gray-50 text-[10px] uppercase tracking-wider text-gray-500 font-bold">
                                <tr>
                                  <th className="px-3 py-2 text-left w-10">#</th>
                                  <th className="px-3 py-2 text-left">Artigo</th>
                                  <th className="px-3 py-2 text-right">Peso (kg)</th>
                                  <th className="px-3 py-2 text-right">Horário</th>
                                  <th className="px-3 py-2 text-right">QTF</th>
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-gray-50">
                                {visibleCestas.map((cesta, i) => (
                                  <tr key={i} className="hover:bg-gray-50/50 transition-colors">
                                    <td className="px-3 py-1.5 text-gray-400 font-mono text-xs">{i + 1}</td>
                                    <td className="px-3 py-1.5 text-gray-600 text-xs truncate max-w-[200px]" title={cesta.articleName}>{cesta.articleName}</td>
                                    <td className="px-3 py-1.5 text-right font-mono font-bold text-blue-700">{cesta.weight.toFixed(3)}</td>
                                    <td className="px-3 py-1.5 text-right font-mono text-gray-600 text-xs">{cesta.time}</td>
                                    <td className="px-3 py-1.5 text-right font-mono text-emerald-600 text-xs">{cesta.qtf}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {hasMore && (
                              <button onClick={() => setRegistrosVisibleCounts(prev => ({ ...prev, [key]: visibleCount + 80 }))}
                                className="mt-3 w-full text-center text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 rounded-lg py-2 transition-colors">
                                Mostrar mais ({allCestas.length - visibleCount} restantes)
                              </button>
                            )}
                            {allCestas.length === 0 && <p className="text-sm text-gray-400 text-center py-8">Nenhuma cesta registrada</p>}
                          </div>
                        );
                      })()}
                    </div>
                  </div>
                );
              })()}
            </div>
          );
        })()}

        {/* Error Message */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl mb-8 flex items-center gap-3"
            >
              <AlertCircle size={20} />
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Results Section */}
        {hasResults && mode !== 'history' && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white rounded-3xl shadow-sm border border-gray-100 overflow-hidden"
          >
            <div className="p-4 sm:p-6 border-bottom border-gray-100 bg-gray-50/50 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-3">
              <div className="flex flex-wrap items-center gap-3 sm:gap-4">
                <h2 className="text-lg sm:text-xl font-bold">Resultados Consolidados</h2>
                <div className="flex bg-white rounded-xl border border-gray-200 p-1 shadow-sm">
                  <button
                    onClick={() => setViewMode('geral')}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
                      viewMode === 'geral' ? "bg-emerald-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                    )}
                  >
                    <TableIcon size={13} />
                    Geral
                  </button>
                  <button
                    onClick={() => setViewMode('grafico')}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
                      viewMode === 'grafico' ? "bg-blue-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                    )}
                  >
                    <BarChart3 size={13} />
                    Gráfico
                  </button>
                  <button
                    onClick={() => setViewMode('registros')}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all",
                      viewMode === 'registros' ? "bg-violet-500 text-white shadow-sm" : "text-gray-500 hover:text-gray-700"
                    )}
                  >
                    <List size={13} />
                    Registros
                  </button>
                </div>
              </div>
              <span className="text-sm text-gray-500 font-medium bg-white px-3 py-1 rounded-full border border-gray-100 shadow-sm">
                {resultCount} registros encontrados
              </span>
            </div>

            {/* Processo & Loja Banner */}
            {(processoBanner || lojaBanner) && (
              <div className="px-6 py-3 bg-violet-50/50 border-b border-violet-100 flex flex-wrap items-center gap-6">
                {processoBanner && (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wider font-bold text-violet-400">Processo</span>
                    <span className="text-sm font-semibold text-violet-700 bg-violet-100 px-3 py-1 rounded-lg">{processoBanner}</span>
                  </div>
                )}
                {lojaBanner && (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] uppercase tracking-wider font-bold text-amber-400">Loja</span>
                    <span className="text-sm font-semibold text-amber-700 bg-amber-100 px-3 py-1 rounded-lg">{lojaBanner}</span>
                    {/* CPM geral ao lado da loja - live mode */}
                    {(() => {
                      const allCpms = sortedResults.map(r => r.cpm ?? 0).filter(c => typeof c === 'number' && !isNaN(c));
                      const avgCpm = allCpms.length > 0 ? (allCpms.reduce((a, b) => a + b, 0) / allCpms.length) : 0;
                      return (
                        <span className="ml-2 text-xs font-bold text-orange-700 bg-orange-50 px-2 py-0.5 rounded-full border border-orange-100">CPM Geral: {avgCpm.toFixed(2)}</span>
                      );
                    })()}
                  </div>
                )}
              </div>
            )}
            
            {viewMode === 'geral' && (
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-gray-50/50 text-gray-500 text-xs uppercase tracking-wider font-semibold">
                    <th className="p-4 w-12"></th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('user')}>
                      <div className="flex items-center gap-1">
                        Embaladora
                        {sortConfig?.field === 'user' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('cdRcsHumano')}>
                      <div className="flex items-center gap-1">
                        CdRH
                        {sortConfig?.field === 'cdRcsHumano' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('nrIdentificacao')}>
                      <div className="flex items-center gap-1">
                        Crachá
                        {sortConfig?.field === 'nrIdentificacao' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('bloqueios')}>
                      <div className="flex items-center gap-1">
                        Bloqueios
                        {sortConfig?.field === 'bloqueios' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('device')}>
                      <div className="flex items-center gap-1">
                        Balança
                        {sortConfig?.field === 'device' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort(mode === 'live' ? 'punnets' : 'productionCount')}>
                      <div className="flex items-center gap-1">
                        Cestas
                        {(sortConfig?.field === 'punnets' || sortConfig?.field === 'productionCount') ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('totalWeight')}>
                      <div className="flex items-center gap-1">
                        Peso Total (kg)
                        {sortConfig?.field === 'totalWeight' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('cpm')}>
                      <div className="flex items-center gap-1">
                        CPM
                        {sortConfig?.field === 'cpm' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('totalWorkingTimeMs')}>
                      <div className="flex items-center gap-1">
                        Tempo Total
                        {sortConfig?.field === 'totalWorkingTimeMs' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                    <th className="p-4 cursor-pointer hover:bg-gray-100 transition-colors" onClick={() => requestSort('totalSessions')}>
                      <div className="flex items-center gap-1">
                        Sessões
                        {sortConfig?.field === 'totalSessions' ? (
                          sortConfig.order === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />
                        ) : <ArrowUpDown size={12} className="text-gray-300" />}
                      </div>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {sortedResults.map((row, idx) => {
                    const rowId = getOperatorIdentityKey(row);
                    const isExpanded = expandedRows.has(rowId);
                    const rowCpm = row.cpm ?? 0;
                    const rowCpmStyles = getCpmStyles(rowCpm);
                    const liveCpmColor = rowCpmStyles.badge;
                    const liveCpmBorderLeft = rowCpmStyles.accent;
                    
                    return (
                      <React.Fragment key={rowId}>
                        <tr 
                          className={cn(
                            "hover:bg-gray-50 transition-colors cursor-pointer group",
                            isExpanded && "bg-blue-50/30"
                          )}
                          onClick={() => toggleRow(rowId)}
                        >
                          <td className="p-4 text-center">
                            {isExpanded ? <ChevronDown size={16} className="text-blue-500" /> : <ChevronRight size={16} className="text-gray-400 group-hover:text-blue-500" />}
                          </td>
                          <td className="p-4 font-medium">{row.user}</td>
                          <td className="p-4">
                            <span className="bg-cyan-50 text-cyan-700 px-2 py-1 rounded text-xs font-mono border border-cyan-100">
                              {(row as any).cdRcsHumano || '-'}
                            </span>
                          </td>
                          <td className="p-4">
                            <span className="bg-indigo-50 text-indigo-700 px-2 py-1 rounded text-xs font-mono border border-indigo-100">
                              {row.nrIdentificacao || '-'}
                            </span>
                          </td>
                          <td className="p-4">
                            <span className="bg-amber-50 text-amber-700 px-2 py-1 rounded text-xs font-mono border border-amber-100">
                              {(row.bloqueios ?? 0)}
                            </span>
                          </td>
                          <td className="p-4">
                            {(() => {
                              let deviceLabel: string;
                              if (mode === 'live') {
                                const activeSessions = row.sessionEntries.filter(
                                  s => !(s as any)['Logout time'] && !(s as any).logoutTime
                                );
                                if (activeSessions.length === 0) {
                                  deviceLabel = '-';
                                } else {
                                  const devices = [...new Set(
                                    activeSessions
                                      .map(s => getSessionDeviceLabel(s as any, ''))
                                      .filter(Boolean)
                                  )];
                                  deviceLabel = devices.length > 0 ? devices.join(' / ') : (row.device || '-');
                                }
                              } else {
                                deviceLabel = row.device;
                              }
                              return (
                                <span className="bg-gray-100 px-2 py-1 rounded text-xs font-mono text-gray-600">
                                  {deviceLabel}
                                </span>
                              );
                            })()}
                          </td>
                          <td className="p-4">
                            {mode === 'live' ? (
                              <span className="inline-flex items-center whitespace-nowrap bg-violet-50 text-violet-700 px-2 py-0.5 rounded-full text-xs font-medium border border-violet-100">
                                {liveData.find(l => getOperatorIdentityKey(l) === rowId)?.totalPunnets ?? row.productionEntries.length} cestas
                              </span>
                            ) : (
                              <span className="inline-flex items-center whitespace-nowrap bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full text-xs font-medium border border-blue-100">
                                {row.productionEntries.length}
                              </span>
                            )}
                          </td>
                          <td className="p-4 font-mono text-blue-600 font-semibold">
                            {row.totalWeight.toFixed(3)}
                          </td>
                          <td className="p-4">
                            <span className={cn("px-2 py-0.5 rounded-full text-xs font-bold border", liveCpmColor)}>
                              {rowCpm.toFixed(2)}
                            </span>
                          </td>
                          <td className="p-4 font-mono text-gray-600">
                            {formatMsToDuration(row.totalWorkingTimeMs)}
                          </td>
                          <td className="p-4">
                            <span className="bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full text-xs font-medium border border-emerald-100">
                              {row.totalSessions}
                            </span>
                          </td>
                        </tr>
                        <AnimatePresence>
                          {isExpanded && (
                            <tr>
                              <td colSpan={11} className="p-0">
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: 'auto', opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  className="overflow-hidden bg-gray-50/80 border-y border-gray-100"
                                >
                                  <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-8">
                                    <div>
                                      <h4 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                        <LayoutGrid size={14} />
                                        Produção por Hora ({row.productionEntries.length})
                                      </h4>
                                      <div className="max-h-60 overflow-y-auto space-y-2 pr-2 custom-scrollbar">
                                        {row.productionEntries.map((p, i) => {
                                          const productionCpm = getProductionEntryCpm(p as ProductionSlotEntry, row.sessionEntries as SessionSlotEntry[], rowCpm);
                                          const productionCpmStyles = getCpmStyles(productionCpm);
                                          return (
                                          <div key={i} className={cn("bg-white p-3 rounded-lg border border-gray-100 text-sm", productionCpmStyles.accent)}>
                                            <div className="flex justify-between items-start mb-1">
                                              <p className="font-medium">{p['Article name']}</p>
                                              <p className="font-mono font-bold text-blue-600">{Number(p['Net weight [kg]']).toFixed(3)}kg</p>
                                            </div>
                                            <div className="flex items-center gap-3 text-xs text-gray-500">
                                              <span className={cn("font-mono px-1.5 py-0.5 rounded", productionCpmStyles.badge)}>{getProductionTimeLabel(p as ProductionSlotEntry)}</span>
                                              <span className="text-violet-600 font-semibold">{(p as any)._punnets ?? '-'} cestas</span>
                                              <span>avg {((p as any)._avgWeight ?? 0).toFixed(3)}kg</span>
                                              <span className={cn("px-1.5 py-0.5 rounded-full font-bold border", productionCpmStyles.badge)}>CPM {productionCpm.toFixed(2)}</span>
                                            </div>
                                          </div>
                                        );})}
                                      </div>
                                    </div>
                                    <div>
                                      <h4 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                        <TableIcon size={14} />
                                        Sessões de Trabalho ({row.sessionEntries.length})
                                      </h4>
                                      <div className="max-h-60 overflow-y-auto space-y-2 pr-2 custom-scrollbar">
                                        {row.sessionEntries.map((s, i) => {
                                          const loginStr = s['Login time'] ? new Date(s['Login time']).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
                                          const logoutStr = s['Logout time'] ? new Date(s['Logout time']).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'ativa';
                                          const timeDisplay = loginStr ? `${loginStr} → ${logoutStr}` : '';
                                          const deviceLabel = getSessionDeviceLabel(s, row.device);
                                          return (
                                            <div key={i} className="bg-white p-3 rounded-lg border border-gray-100 text-sm">
                                              <div className="flex justify-between items-start mb-1">
                                                <div>
                                                  <p className="font-medium">{s.Activity || 'Sessão'}</p>
                                                  {s.Line && <p className="text-[10px] text-gray-400">{s.Line}</p>}
                                                  {deviceLabel && <p className="text-[10px] text-gray-400">Balança {deviceLabel}</p>}
                                                </div>
                                                <p className="font-mono text-emerald-600 font-semibold">{s['Working time']}</p>
                                              </div>
                                              {timeDisplay && (
                                                <p className="text-xs text-gray-500 font-mono bg-gray-50 px-2 py-0.5 rounded inline-block">
                                                  {timeDisplay}
                                                </p>
                                              )}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  </div>
                                </motion.div>
                              </td>
                            </tr>
                          )}
                        </AnimatePresence>
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            )}

            {/* Gráfico View - Vertical Bar Chart by Cestas */}
            {viewMode === 'grafico' && (() => {
              const dataSource = mode === 'live' ? liveData : [];
              // Sort by cestas descending for chart ordering AND color ranking
              const sortedByCestas = [...dataSource].sort((a, b) => b.totalPunnets - a.totalPunnets);
              const totalOps = dataSource.length;
              const greenLimit = Math.ceil(totalOps / 3);
              const yellowLimit = Math.ceil((totalOps * 2) / 3);
              const getColor = (cestasRank: number) => {
                if (cestasRank < greenLimit) return { bar: 'bg-emerald-500', text: 'text-emerald-700', dot: 'bg-emerald-400' };
                if (cestasRank < yellowLimit) return { bar: 'bg-yellow-500', text: 'text-yellow-700', dot: 'bg-yellow-400' };
                return { bar: 'bg-red-500', text: 'text-red-700', dot: 'bg-red-400' };
              };
              const getCestasRank = (entry: typeof dataSource[0]) => sortedByCestas.findIndex(e => getOperatorIdentityKey(e) === getOperatorIdentityKey(entry));
              const filtered = chartSelectedOps.size > 0 ? sortedByCestas.filter(e => chartSelectedOps.has(getOperatorIdentityKey(e))) : sortedByCestas;
              const maxPunnets = Math.max(...(chartSelectedOps.size > 0 ? filtered : sortedByCestas).map(e => e.totalPunnets), 1);
              const chartH = chartFullscreen ? 600 : 400;
              const gridSteps = 5;
              const gridLines = Array.from({ length: gridSteps + 1 }, (_, i) => Math.round((maxPunnets / gridSteps) * (gridSteps - i)));

              const toggleChartOp = (key: string) => {
                const next = new Set(chartSelectedOps);
                if (next.has(key)) next.delete(key); else next.add(key);
                setChartSelectedOps(next);
              };

              // Bar width for each column
              const barW = filtered.length <= 8 ? 72 : filtered.length <= 15 ? 50 : 34;
              const totalChartW = Math.max(filtered.length * (barW + 4) + 44, 400);

              return (
                <motion.div
                  layout
                  transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
                  className={cn(
                    "flex",
                    chartFullscreen ? "fixed inset-0 z-50 bg-white shadow-2xl" : ""
                  )}
                  style={{ minHeight: chartFullscreen ? '100vh' : '550px' }}
                >
                  {/* Left panel - operator list (multi-select) */}
                  <div className={cn("w-[20%] border-r border-gray-100 overflow-y-auto", chartFullscreen ? "h-screen" : "")} style={chartFullscreen ? {} : { maxHeight: '600px' }}>
                    <div className="p-3">
                      <button
                        onClick={() => setChartFullscreen(!chartFullscreen)}
                        className="w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all mb-2 bg-gray-100 text-gray-600 hover:bg-gray-200"
                      >
                        {chartFullscreen ? '✕ Fechar Tela Cheia' : '⛶ Tela Cheia'}
                      </button>
                      <button
                        onClick={() => setChartSelectedOps(new Set())}
                        className={cn(
                          "w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition-all mb-1",
                          chartSelectedOps.size === 0 ? "bg-blue-500 text-white shadow-sm" : "text-gray-600 hover:bg-gray-50"
                        )}
                      >
                        Todas
                      </button>
                      {sortedByCestas.map((entry, idx) => {
                        const colors = getColor(idx);
                        const opKey = getOperatorIdentityKey(entry);
                        const isSelected = chartSelectedOps.has(opKey);
                        return (
                          <button
                            key={opKey}
                            onClick={() => toggleChartOp(opKey)}
                            className={cn(
                              "w-full text-left px-3 py-2 rounded-lg text-sm transition-all mb-0.5 flex items-center gap-2",
                              isSelected ? "bg-blue-50 text-blue-700 font-semibold ring-1 ring-blue-200" : "text-gray-600 hover:bg-gray-50"
                            )}
                          >
                            <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", colors.dot)} />
                            <div className="flex flex-col min-w-0">
                              <span className="truncate">{entry.user}</span>
                              <div className="flex gap-1.5 text-[9px] font-mono text-gray-400">
                                <span>{entry.cdRcsHumano || '-'}</span>
                                <span>·</span>
                                <span>{entry.nrIdentificacao || '-'}</span>
                              </div>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Right panel - vertical bar chart */}
                  <motion.div layout className="w-[80%] p-6 overflow-x-auto overflow-y-hidden">
                    <div className="relative" style={{ height: chartH + 80, minWidth: totalChartW }}>
                      {/* Y-axis grid lines */}
                      {gridLines.map((val, i) => {
                        const top = (i / gridSteps) * chartH;
                        return (
                          <div key={i} className="absolute w-full flex items-center" style={{ top, left: 0, right: 0 }}>
                            <span className="text-[10px] text-gray-400 font-mono w-10 text-right pr-2 shrink-0">{val}</span>
                            <div className="flex-1 border-t border-gray-200" />
                          </div>
                        );
                      })}

                      {/* Bars + labels - sorted by cestas desc, animated reorder */}
                      <div className="absolute flex gap-1 items-end" style={{ left: 44, right: 0, bottom: 0, height: chartH + 80 }}>
                        {filtered.map((entry, filtIdx) => {
                          const cestasRank = getCestasRank(entry);
                          const barHeightPx = Math.max(Math.round((entry.totalPunnets / maxPunnets) * chartH), 4);
                          const colors = getColor(cestasRank);

                          return (
                            <motion.div
                              key={getOperatorIdentityKey(entry)}
                              layout
                              transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
                              className="flex flex-col items-center justify-end"
                              style={{ width: barW, minWidth: barW, flexShrink: 0 }}
                            >
                              {/* Value label */}
                              <motion.span
                                layout
                                className="text-[10px] font-bold text-gray-600 mb-1 whitespace-nowrap"
                              >
                                {entry.totalPunnets}
                              </motion.span>
                              {/* Bar */}
                              <motion.div
                                layout
                                animate={{ height: barHeightPx }}
                                transition={{ duration: 0.6, ease: [0.4, 0, 0.2, 1] }}
                                className={cn("w-full rounded-t-md shadow-sm", colors.bar)}
                                title={`${entry.user}\nCestas: ${entry.totalPunnets}\nPeso: ${entry.totalWeight.toFixed(3)} kg`}
                              />
                              {/* Name label */}
                              <div className="h-16 flex items-start justify-center pt-1 overflow-hidden" style={{ width: '100%' }}>
                                <span className={cn("text-[9px] font-semibold", colors.text)}
                                  style={{ writingMode: 'vertical-rl', textOrientation: 'mixed', maxHeight: 58, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                                >
                                  {entry.user}
                                </span>
                              </div>
                            </motion.div>
                          );
                        })}
                      </div>
                    </div>
                  </motion.div>
                </motion.div>
              );
            })()}

            {/* Registros View - List layout with sidebar */}
            {viewMode === 'registros' && (() => {
              const dataSource = mode === 'live' ? liveData : [];
              const sorted = [...dataSource].sort((a, b) => b.totalPunnets - a.totalPunnets);
              const totalOpsR = sorted.length;
              const greenLimitR = Math.ceil(totalOpsR / 3);
              const yellowLimitR = Math.ceil((totalOpsR * 2) / 3);
              const getColorR = (rank: number) => {
                if (rank < greenLimitR) return { dot: 'bg-emerald-400', accent: 'border-emerald-200 bg-emerald-50/30', badge: 'bg-emerald-50 text-emerald-700 border-emerald-100' };
                if (rank < yellowLimitR) return { dot: 'bg-yellow-400', accent: 'border-yellow-200 bg-yellow-50/30', badge: 'bg-yellow-50 text-yellow-700 border-yellow-100' };
                return { dot: 'bg-red-400', accent: 'border-red-200 bg-red-50/30', badge: 'bg-red-50 text-red-700 border-red-100' };
              };

              const selectedRegOp = registrosExpandedOps.size > 0 ? [...registrosExpandedOps][0] : null;
              const selectedEntry = selectedRegOp ? sorted.find(e => getOperatorIdentityKey(e) === selectedRegOp) : null;

              const toggleOp = (key: string) => {
                setRegistrosExpandedOps(new Set(registrosExpandedOps.has(key) ? [] : [key]));
              };

              return (
                <div className="flex" style={{ minHeight: 550 }}>
                  {/* Left panel - operator list */}
                  <div className="w-[25%] border-r border-gray-100 overflow-y-auto" style={{ maxHeight: 650 }}>
                    <div className="p-3">
                      {sorted.map((entry, idx) => {
                        const colors = getColorR(idx);
                        const opKey = getOperatorIdentityKey(entry);
                        const isSelected = opKey === selectedRegOp;
                        const cpm = entry.cpm || (entry.totalWorkingTimeMs > 0 ? entry.totalPunnets / (entry.totalWorkingTimeMs / 60000) : 0);
                        const cpmStyles = getCpmStyles(cpm);
                        return (
                          <button
                            key={opKey}
                            onClick={() => toggleOp(opKey)}
                            className={cn(
                              "w-full text-left px-3 py-2.5 rounded-lg text-sm transition-all mb-0.5",
                              isSelected ? "bg-blue-50 ring-1 ring-blue-200 shadow-sm" : "hover:bg-gray-50"
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <span className={cn("w-2.5 h-2.5 rounded-full shrink-0", colors.dot)} />
                              <span className={cn("font-semibold truncate", isSelected ? "text-blue-700" : "text-gray-700")}>{entry.user}</span>
                            </div>
                            <div className="flex items-center gap-2 mt-1 ml-4.5 text-[10px] text-gray-400 font-mono">
                              <span>{entry.cdRcsHumano || '-'}</span>
                              <span>·</span>
                              <span>{entry.nrIdentificacao || '-'}</span>
                              <span>·</span>
                              <span>{entry.device}</span>
                            </div>
                            <div className="flex items-center gap-3 mt-1 ml-4.5 text-[10px]">
                              <span className="font-bold text-violet-600">{entry.totalPunnets} cestas</span>
                              <span className="font-bold text-blue-600">{entry.totalWeight.toFixed(1)} kg</span>
                              <span className={cn("px-1.5 py-0.5 rounded-full font-bold border text-[9px]", cpmStyles.badge)}>CPM {cpm.toFixed(2)}</span>
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Right panel - cestas detail */}
                  <div className="w-[75%] p-4 overflow-y-auto" style={{ maxHeight: 650 }}>
                    {!selectedEntry ? (
                      <div className="flex items-center justify-center h-full text-gray-400">
                        <div className="text-center">
                          <List size={48} className="mx-auto mb-4 text-gray-300" />
                          <p className="text-lg font-medium">Selecione um operador</p>
                          <p className="text-sm mt-1">Clique em um nome à esquerda para ver os registros individuais</p>
                        </div>
                      </div>
                    ) : (() => {
                      const entry = selectedEntry;
                      const cestasRank = sorted.findIndex(e => getOperatorIdentityKey(e) === getOperatorIdentityKey(entry));
                      const colors = getColorR(cestasRank);
                      const cpm = entry.cpm || (entry.totalWorkingTimeMs > 0 ? entry.totalPunnets / (entry.totalWorkingTimeMs / 60000) : 0);
                      const cpmStyles = getCpmStyles(cpm);
                      const allCestas: { articleName: string; weight: number; time: string; qtf: string }[] = [];
                      entry.productionEntries.forEach(p => {
                        const slotBase = p.registeredAt ? new Date(p.registeredAt) : null;
                        const slotMinutesPerCesta = p.punnets > 0 ? 60 / p.punnets : 0;
                        const qtfStr = formatMsToDuration(slotMinutesPerCesta * 60000);
                        for (let c = 0; c < p.punnets; c++) {
                          let timeStr = p.timeRange || '-';
                          if (slotBase) {
                            const cestaTime = new Date(slotBase.getTime() + c * slotMinutesPerCesta * 60000);
                            timeStr = cestaTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                          }
                          allCestas.push({ articleName: p.articleName, weight: p.avgWeight, time: timeStr, qtf: qtfStr });
                        }
                      });
                      const key = getOperatorIdentityKey(entry);
                      const visibleCount = registrosVisibleCounts[key] || 80;
                      const visibleCestas = allCestas.slice(0, visibleCount);
                      const hasMore = allCestas.length > visibleCount;

                      return (
                        <div>
                          {/* Header */}
                          <div className="flex items-center justify-between mb-4 pb-3 border-b border-gray-100">
                            <div className="flex items-center gap-3">
                              <span className={cn("w-3 h-3 rounded-full", colors.dot)} />
                              <span className="font-bold text-lg text-gray-800">{entry.user}</span>
                              <span className="bg-cyan-50 text-cyan-700 px-2 py-0.5 rounded text-xs font-mono border border-cyan-100">{entry.cdRcsHumano || '-'}</span>
                              <span className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded text-xs font-mono border border-indigo-100">{entry.nrIdentificacao || '-'}</span>
                              <span className="bg-gray-100 px-2 py-0.5 rounded text-xs font-mono text-gray-500">{entry.device}</span>
                            </div>
                            <div className="flex items-center gap-4 text-sm">
                              <span className="font-mono font-bold text-violet-600">{entry.totalPunnets} cestas</span>
                              <span className="font-mono font-bold text-blue-600">{entry.totalWeight.toFixed(3)} kg</span>
                                <span className={cn("px-2 py-0.5 rounded-full font-bold border text-xs", cpmStyles.badge)}>CPM {cpm.toFixed(2)}</span>
                              <span className="text-gray-400 font-mono text-xs">{formatMsToDuration(entry.totalWorkingTimeMs)}</span>
                            </div>
                          </div>
                          {/* Cestas table */}
                          <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-gray-50 text-[10px] uppercase tracking-wider text-gray-500 font-bold">
                              <tr>
                                <th className="px-3 py-2 text-left w-10">#</th>
                                <th className="px-3 py-2 text-left">Artigo</th>
                                <th className="px-3 py-2 text-right">Peso (kg)</th>
                                <th className="px-3 py-2 text-right">Horário</th>
                                <th className="px-3 py-2 text-right">QTF</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50">
                              {visibleCestas.map((cesta, i) => (
                                <tr key={i} className="hover:bg-gray-50/50 transition-colors">
                                  <td className="px-3 py-1.5 text-gray-400 font-mono text-xs">{i + 1}</td>
                                  <td className="px-3 py-1.5 text-gray-600 text-xs truncate max-w-[200px]" title={cesta.articleName}>{cesta.articleName}</td>
                                  <td className="px-3 py-1.5 text-right font-mono font-bold text-blue-700">{cesta.weight.toFixed(3)}</td>
                                  <td className="px-3 py-1.5 text-right font-mono text-gray-600 text-xs">{cesta.time}</td>
                                  <td className="px-3 py-1.5 text-right font-mono text-emerald-600 text-xs">{cesta.qtf}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          {hasMore && (
                            <button
                              onClick={() => setRegistrosVisibleCounts(prev => ({ ...prev, [key]: visibleCount + 80 }))}
                              className="mt-3 w-full text-center text-xs font-semibold text-blue-600 hover:text-blue-800 bg-blue-50 rounded-lg py-2 transition-colors"
                            >
                              Mostrar mais ({allCestas.length - visibleCount} restantes)
                            </button>
                          )}
                          {allCestas.length === 0 && <p className="text-sm text-gray-400 text-center py-8">Nenhuma cesta registrada</p>}
                        </div>
                      );
                    })()}
                  </div>
                </div>
              );
            })()}
          </motion.div>
        )}
      </div>
    </div>
  );
}

interface FileDropZoneProps {
  title: string;
  description: string;
  files: File[];
  onFilesSelect: (files: FileList | File[]) => void;
  onRemoveFile: (index: number) => void;
  icon: React.ReactNode;
}

function FileDropZone({ title, description, files, onFilesSelect, onRemoveFile, icon }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFiles = e.dataTransfer.files;
    if (droppedFiles.length > 0) {
      onFilesSelect(droppedFiles);
    }
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={cn(
        "relative border-2 border-dashed rounded-3xl p-8 transition-all flex flex-col items-center justify-center text-center gap-4 group min-h-[300px]",
        isDragging ? "border-blue-500 bg-blue-50" : "border-gray-200 bg-white hover:border-gray-300",
        files.length > 0 && "border-emerald-500 bg-emerald-50/10"
      )}
    >
      <div className={cn(
        "w-16 h-16 rounded-2xl flex items-center justify-center mb-2 transition-transform group-hover:scale-110",
        files.length > 0 ? "bg-emerald-100 text-emerald-600" : "bg-gray-50 text-gray-400"
      )}>
        {files.length > 0 ? <CheckCircle2 size={32} /> : icon}
      </div>
      
      <div>
        <h3 className="font-bold text-lg">{title}</h3>
        <p className="text-gray-500 text-sm max-w-[240px] mx-auto">{description}</p>
      </div>

      {files.length > 0 && (
        <div className="w-full mt-4 space-y-2 max-h-40 overflow-y-auto pr-2 custom-scrollbar">
          {files.map((file, idx) => (
            <div key={`${file.name}-${idx}`} className="bg-white border border-gray-100 p-2 rounded-lg flex items-center justify-between text-sm shadow-sm">
              <div className="flex items-center gap-2 overflow-hidden">
                <FileText size={14} className="text-gray-400 shrink-0" />
                <span className="truncate font-medium">{file.name}</span>
              </div>
              <button 
                onClick={(e) => { e.stopPropagation(); onRemoveFile(idx); }}
                className="text-gray-400 hover:text-red-500 transition-colors p-1"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      <label className="mt-4 cursor-pointer bg-white border border-gray-200 px-6 py-2 rounded-xl text-sm font-semibold hover:bg-gray-50 transition-colors shadow-sm">
        Adicionar Arquivos
        <input
          type="file"
          className="hidden"
          accept=".xlsx, .xls"
          multiple
          onChange={(e) => e.target.files && onFilesSelect(e.target.files)}
        />
      </label>
    </div>
  );
}
