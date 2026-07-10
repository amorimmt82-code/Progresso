import * as XLSX from 'xlsx';

export interface ProductionData {
  'Registered at': string | Date;
  'Article name': string;
  'Device name': string;
  'Users': string;
  'Net weight [kg]': number;
  'Tare [kg]': number;
  'Type': string;
}

export interface SessionData {
  'User': string;
  'Line': string;
  'Device': string;
  'Activity': string;
  'Working time': string;
  'Login time': string | Date;
  'Logout time': string | Date;
}

export interface GroupedData {
  user: string;
  device: string;
  totalWeight: number;
  totalSessions: number;
  articles: string[];
  totalWorkingTimeMs: number;
  bloqueios?: number;
  productionEntries: ProductionData[];
  sessionEntries: SessionData[];
  customers?: string[];
  currentArticle?: string;
  currentCustomer?: string;
  nrIdentificacao?: string;
  cdRcsHumano?: string;
  cpm?: number;
}

export const parseExcel = async <T>(file: File): Promise<T[]> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        const workbook = XLSX.read(data, { type: 'binary', cellDates: true });
        const firstSheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[firstSheetName];
        const jsonData = XLSX.utils.sheet_to_json(worksheet) as T[];
        resolve(jsonData);
      } catch (error) {
        reject(error);
      }
    };
    reader.onerror = (error) => reject(error);
    reader.readAsBinaryString(file);
  });
};

export const parseDurationToMs = (duration: any): number => {
  if (duration === null || duration === undefined) return 0;

  // Handle Excel serial time (number)
  if (typeof duration === 'number') {
    return Math.round(duration * 24 * 60 * 60 * 1000);
  }

  if (typeof duration !== 'string') return 0;
  
  const parts = duration.split(':').map(Number);
  
  if (parts.length === 4) {
    // Format: Days:Hours:Minutes:Seconds
    const [days, hours, minutes, seconds] = parts;
    return (((days * 24 + hours) * 3600) + (minutes * 60) + seconds) * 1000;
  }
  
  if (parts.length === 3) {
    // Format: Hours:Minutes:Seconds
    const [hours, minutes, seconds] = parts;
    return (hours * 3600 + minutes * 60 + seconds) * 1000;
  }

  if (parts.length === 2) {
    // Format: Minutes:Seconds
    const [minutes, seconds] = parts;
    return (minutes * 60 + seconds) * 1000;
  }
  
  // Try to parse as a single number if it's a string containing only digits
  if (/^\d+(\.\d+)?$/.test(duration)) {
    return Math.round(parseFloat(duration) * 24 * 60 * 60 * 1000);
  }

  return 0;
};

export const formatMsToDuration = (ms: number): string => {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
};

export const groupData = (production: ProductionData[], sessions: SessionData[]): GroupedData[] => {
  const groupedMap = new Map<string, GroupedData>();

  // Process production data
  production.forEach((entry) => {
    const key = `${entry.Users}-${entry['Device name']}`;
    if (!groupedMap.has(key)) {
      groupedMap.set(key, {
        user: entry.Users,
        device: entry['Device name'],
        totalWeight: 0,
        totalSessions: 0,
        articles: [],
        totalWorkingTimeMs: 0,
        productionEntries: [],
        sessionEntries: [],
      });
    }

    const group = groupedMap.get(key)!;
    group.totalWeight += Number(entry['Net weight [kg]']) || 0;
    if (!group.articles.includes(entry['Article name'])) {
      group.articles.push(entry['Article name']);
    }
    group.productionEntries.push(entry);
  });

  // Process session data
  sessions.forEach((entry) => {
    const key = `${entry.User}-${entry.Device}`;
    if (!groupedMap.has(key)) {
      groupedMap.set(key, {
        user: entry.User,
        device: entry.Device,
        totalWeight: 0,
        totalSessions: 0,
        articles: [],
        totalWorkingTimeMs: 0,
        productionEntries: [],
        sessionEntries: [],
      });
    }

    const group = groupedMap.get(key)!;
    group.totalSessions += 1;
    group.totalWorkingTimeMs += parseDurationToMs(entry['Working time']);
    group.sessionEntries.push(entry);
  });

  return Array.from(groupedMap.values());
};
