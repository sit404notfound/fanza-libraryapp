import React, { useState, useEffect, useRef } from 'react';
import { 
  Search, Settings, RefreshCw, Play, Download, User, 
  ExternalLink, Lock, Sun, Moon, Calendar, DollarSign, 
  CheckCircle, AlertCircle, Loader, Volume2, BookOpen, X, Terminal,
  Maximize2, Minimize2, Folder, Wrench
} from 'lucide-react';
import type { Work, WorkDetail, SyncStatus, AuthStatus, DownloadStatus } from './types';

export default function App() {
  // テーマ状態 (dark/light)
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  
  // 状態管理
  const [works, setWorks] = useState<Work[]>([]);
  const [selectedWorkId, setSelectedWorkId] = useState<string | null>(null);
  const [selectedWork, setSelectedWork] = useState<WorkDetail | null>(null);
  
  // 検索・フィルタ・ソート条件
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedGenre, setSelectedGenre] = useState<string>('all');
  const [selectedMylist, setSelectedMylist] = useState<string>('all');
  const [showStreamingOnly, setShowStreamingOnly] = useState(false);
  const [downloadStatusFilter, setDownloadStatusFilter] = useState<'all' | 'downloaded' | 'not_downloaded'>('all');
  const [sortKey, setSortKey] = useState<string>('purchase_date');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('desc');

  // モーダル表示状態
  const [showLoginModal, setShowLoginModal] = useState(false);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [showPlayerModal, setShowPlayerModal] = useState(false);

  // 認証関連
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [twoFactorCode, setTwoFactorCode] = useState('');
  const [authStatus, setAuthStatus] = useState<AuthStatus>({ status: 'IDLE', error_message: null });
  const [sessionStatus, setSessionStatus] = useState<{ authenticated: boolean; status: string; message: string }>({ authenticated: false, status: 'UNKNOWN', message: '確認中...' });

  // 同期・SSE関連
  const [syncStatus, setSyncStatus] = useState<SyncStatus>({ status: 'idle', current: 0, total: 0, message: '' });
  const [syncLogs, setSyncLogs] = useState<string[]>([]);
  const sseSourceRef = useRef<EventSource | null>(null);

  // ダウンロード進捗状況 {cid: DownloadStatus}
  const [downloadProgresses, setDownloadProgresses] = useState<Record<string, DownloadStatus>>({});

  // 設定関連
  const [downloadDir, setDownloadDir] = useState('');
  const [downloadsInfo, setDownloadsInfo] = useState<{ total_size_str: string; files: any[] } | null>(null);
  
  // ジャンル・マイリストのリスト (UI絞り込み用)
  const [genres, setGenres] = useState<string[]>([]);
  const [mylists, setMylists] = useState<string[]>([]);

  // 購入価格手動編集関連のステート
  const [editingPurchasePrice, setEditingPurchasePrice] = useState<string>('');
  const [isEditingPrice, setIsEditingPrice] = useState(false);

  // 1. 初回起動時のデータロードおよび初期設定
  useEffect(() => {
    // テーマの初期化
    const savedTheme = localStorage.getItem('theme') as 'dark' | 'light' | null;
    if (savedTheme) {
      setTheme(savedTheme);
    }
    
    fetchWorks();
    fetchSettings();
    checkAuthStatus();
    setupSyncSSE();
    checkSession();

    const sessionInterval = setInterval(checkSession, 300000);

    return () => {
      if (sseSourceRef.current) {
        sseSourceRef.current.close();
      }
      clearInterval(sessionInterval);
    };
  }, []);

  // テーマ適用
  useEffect(() => {
    const root = window.document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    localStorage.setItem('theme', theme);
  }, [theme]);

  // 作品一覧の取得処理
  const fetchWorks = async () => {
    try {
      // フィルタ・ソートパラメータの組み立て
      const params = new URLSearchParams();
      if (searchQuery) params.append('q', searchQuery);
      if (selectedGenre !== 'all') params.append('genre', selectedGenre);
      if (selectedMylist !== 'all') params.append('mylist', selectedMylist);
      if (showStreamingOnly) params.append('streaming', 'true');
      if (downloadStatusFilter === 'downloaded') params.append('downloaded', 'true');
      if (downloadStatusFilter === 'not_downloaded') params.append('downloaded', 'false');
      params.append('sort', sortKey);
      params.append('direction', sortDirection);

      const res = await fetch(`/api/works?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setWorks(data);
        
        // 絞り込みフィルター未適用時のみ、ジャンル・マイリスト一覧の選択肢を更新
        if (!searchQuery && selectedGenre === 'all' && selectedMylist === 'all' && !showStreamingOnly && downloadStatusFilter === 'all') {
          extractFilters(data);
        }
      }
    } catch (e) {
      console.error("作品一覧の取得に失敗しました", e);
    }
  };

  // 検索条件変更時のフェッチ (デバウンスなしでシンプルにトリガー)
  useEffect(() => {
    fetchWorks();
  }, [searchQuery, selectedGenre, selectedMylist, showStreamingOnly, downloadStatusFilter, sortKey, sortDirection]);

  // 設定の取得処理
  const fetchSettings = async () => {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        setDownloadDir(data.download_dir);
      }
    } catch {}
  };

  // ダウンロード容量・ファイル情報の取得処理
  const fetchDownloadsInfo = async () => {
    try {
      const res = await fetch('/api/downloads/info');
      if (res.ok) {
        const data = await res.json();
        setDownloadsInfo(data);
      }
    } catch (err) {
      console.error("ダウンロード情報取得失敗", err);
    }
  };

  // ダウンロード済みファイルの一括削除処理
  const handleDeleteAllDownloads = async () => {
    if (!window.confirm("ダウンロード済みのすべてのファイルを物理削除し、作品との紐付けを解除します。よろしいですか？")) {
      return;
    }
    try {
      const res = await fetch('/api/downloads', { method: 'DELETE' });
      if (res.ok) {
        alert("すべてのダウンロードファイルを削除しました。");
        fetchDownloadsInfo();
        fetchWorks();
      } else {
        const data = await res.json();
        alert(`削除に失敗しました: ${data.error || '不明なエラー'}`);
      }
    } catch (err) {
      console.error("一括削除失敗", err);
      alert("通信エラーが発生しました。");
    }
  };

  // 設定モーダル表示時にダウンロード情報を更新
  useEffect(() => {
    if (showSettingsModal) {
      fetchDownloadsInfo();
    }
  }, [showSettingsModal]);

  // ログイン状態の確認処理
  const checkAuthStatus = async () => {
    try {
      const res = await fetch('/api/auth/status');
      if (res.ok) {
        const data = await res.json();
        setAuthStatus(data);
      }
    } catch {}
  };

  // セッション有効性確認処理
  const checkSession = async () => {
    try {
      const res = await fetch('/api/auth/session-check');
      if (res.ok) {
        const data = await res.json();
        setSessionStatus(data);
      }
    } catch {
      setSessionStatus({ authenticated: false, status: 'ERROR', message: 'セッション確認エラー' });
    }
  };

  // 同期用SSEの設定処理
  const setupSyncSSE = () => {
    if (sseSourceRef.current) {
      sseSourceRef.current.close();
    }

    const source = new EventSource('/api/sync/events');
    sseSourceRef.current = source;

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SyncStatus;
        setSyncStatus(data);
        
        // 進捗メッセージをログに追加
        if (data.message) {
          setSyncLogs(prev => [data.message, ...prev.slice(0, 49)]);
        }

        // 同期完了または失敗時は作品一覧を再ロード
        if (data.status === 'complete' || data.status === 'failed') {
          fetchWorks();
        }
      } catch (e) {
        console.error(e);
      }
    };

    source.onerror = () => {
      // エラー発生時の処理 (再接続はブラウザが自動で行う)
    };
  };

  // フィルタ用パラメータ抽出
  const extractFilters = (workList: Work[]) => {
    const uniqueGenres = new Set<string>();
    workList.forEach(w => {
      if (w.genre) uniqueGenres.add(w.genre);
    });
    setGenres(Array.from(uniqueGenres));
    
    // マイリストは詳細データから取得するため、必要に応じて後で補完するが、
    // ここでは簡易的に全マイリスト一覧を作成する
    // 今回は全件API側で管理されているため、フロントでは大分類のみ簡易に扱う
  };

  // 作品詳細のロード処理
  const loadWorkDetail = async (cid: string) => {
    setSelectedWorkId(cid);
    setSelectedWork(null);
    try {
      const res = await fetch(`/api/works/${cid}`);
      if (res.ok) {
        const data = await res.json();
        setSelectedWork(data);
        setEditingPurchasePrice(data.purchase_price !== null ? data.purchase_price.toString() : '');
        setIsEditingPrice(false);
        
        // マイリスト一覧の更新に備え、マイリストを登録
        if (data.mylists) {
          setMylists(prev => {
            const next = new Set([...prev, ...data.mylists]);
            return Array.from(next);
          });
        }

        // ダウンロード進捗のポーリング開始
        pollDownloadStatus(cid);
      }
    } catch {}
  };

  // 手動入力した購入価格の保存処理
  const handleSavePurchasePrice = async (cid: string) => {
    try {
      const val = editingPurchasePrice === '' ? null : parseInt(editingPurchasePrice);
      if (editingPurchasePrice !== '' && isNaN(val as any)) {
        alert("数値を入力してください。");
        return;
      }
      const res = await fetch(`/api/works/${cid}/purchase-price`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purchase_price: val })
      });
      if (res.ok) {
        setSelectedWork(prev => prev ? { ...prev, purchase_price: val } : null);
        fetchWorks();
        setIsEditingPrice(false);
      } else {
        const err = await res.json();
        alert(err.error || "保存に失敗しました。");
      }
    } catch {
      alert("通信エラーが発生しました。");
    }
  };

  // ダウンロード進捗ポーリング
  const pollDownloadStatus = async (cid: string) => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/download/status/${cid}`);
        if (res.ok) {
          const data = await res.json() as DownloadStatus;
          setDownloadProgresses(prev => ({ ...prev, [cid]: data }));
          
          if (data.status === 'COMPLETED' || data.status === 'FAILED') {
            // ダウンロード完了または失敗時はポーリング停止
            clearInterval(intervalId);
            fetchWorks(); // ローカルパス更新のため一覧再フェッチ
            // 詳細データも再フェッチしてローカルパスを反映
            const detailRes = await fetch(`/api/works/${cid}`);
            if (detailRes.ok) {
              const detailData = await detailRes.json();
              setSelectedWork(detailData);
            }
          }
        }
      } catch {
        clearInterval(intervalId);
      }
    };

    // 初回実行
    fetchStatus();
    // 1秒ごとにポーリングを実行
    const intervalId = setInterval(fetchStatus, 1000);
  };

  // ログイン状態のポーリング監視
  useEffect(() => {
    if (authStatus.status !== 'LOGGING_IN' && authStatus.status !== 'WAITING_FOR_2FA') {
      return;
    }

    // 定期的な認証ステータスチェック処理の登録
    const intervalId = setInterval(async () => {
      try {
        const res = await fetch('/api/auth/status');
        if (res.ok) {
          const data = await res.json() as AuthStatus;
          setAuthStatus(data);
          
          // ログイン成功時のセッション更新およびモーダル非表示処理
          if (data.status === 'SUCCESS') {
            checkSession();
            setShowLoginModal(false);
          }
        }
      } catch (err) {
        console.error("認証ステータスの取得に失敗しました", err);
      }
    }, 1500);

    // クリーンアップ処理でのタイマー解除
    return () => clearInterval(intervalId);
  }, [authStatus.status]);

  // ログイン処理の開始
  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthStatus({ status: 'LOGGING_IN', error_message: null });
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
      });
      if (!res.ok) {
        const data = await res.json();
        setAuthStatus({ status: 'FAILED', error_message: data.error });
      }
    } catch (err: any) {
      setAuthStatus({ status: 'FAILED', error_message: err.message });
    }
  };

  // 二段階認証コードの送信
  const handle2FASubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/auth/2fa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: twoFactorCode })
      });
      if (res.ok) {
        setAuthStatus(prev => ({ ...prev, status: 'LOGGING_IN' }));
      } else {
        const data = await res.json();
        setAuthStatus({ status: 'FAILED', error_message: data.error || '二段階認証に失敗しました。' });
      }
    } catch (err: any) {
      setAuthStatus({ status: 'FAILED', error_message: err.message });
    }
  };

  // 同期の開始処理
  const handleStartSync = async (mode: 'quick' | 'full' | 'repair') => {
    try {
      const res = await fetch('/api/sync/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
      });
      if (res.ok) {
        setSyncLogs([]);
      } else {
        const err = await res.json();
        alert(err.error);
      }
    } catch (e) {
      alert("同期開始に失敗しました。");
    }
  };

  // ダウンロードの実行処理
  const handleDownload = async (cid: string) => {
    try {
      const res = await fetch(`/api/works/${cid}/download`, {
        method: 'POST'
      });
      if (res.ok) {
        pollDownloadStatus(cid);
      } else {
        const err = await res.json();
        alert(err.error);
      }
    } catch (e) {
      alert("ダウンロード開始に失敗しました。");
    }
  };

  // 設定の更新処理
  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ download_dir: downloadDir })
      });
      if (res.ok) {
        alert("設定を保存しました。");
        setShowSettingsModal(false);
      } else {
        const err = await res.json();
        alert(err.error);
      }
    } catch {
      alert("設定の保存に失敗しました。");
    }
  };

  // GUIフォルダ選択ダイアログの表示処理
  const handleSelectDirectory = async () => {
    try {
      const res = await fetch('/api/settings/select-directory', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.directory) {
          setDownloadDir(data.directory);
        }
      } else {
        const err = await res.json();
        alert(err.error || "フォルダの選択に失敗しました。");
      }
    } catch {
      alert("通信エラーが発生しました。");
    }
  };

  // データベース全削除の実行処理
  const handleClearDatabase = async () => {
    if (!window.confirm("本当にデータベース内のすべての作品データを削除しますか？\n(ダウンロードしたローカルファイル自体は削除されません)")) {
      return;
    }
    
    try {
      const res = await fetch('/api/database/clear', {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        alert(data.message);
        fetchWorks();
        setShowSettingsModal(false);
      } else {
        const err = await res.json();
        alert(err.error);
      }
    } catch {
      alert("データベースの初期化に失敗しました。");
    }
  };

  return (
    <div className={`min-h-screen transition-colors duration-300 ${theme === 'dark' ? 'bg-[#0a0b10] text-[#a0a6cc]' : 'bg-[#f4f5f9] text-[#2c304d]'}`}>
      
      {/* ヘッダーセクション */}
      <header className={`sticky top-0 z-40 backdrop-blur-md border-b flex justify-between items-center px-6 py-4 ${theme === 'dark' ? 'bg-[#0f111a]/80 border-white/5 shadow-[0_4px_30px_rgba(0,0,0,0.5)]' : 'bg-white/80 border-slate-200 shadow-sm'}`}>
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-violet-600 to-indigo-600 p-2.5 rounded-xl shadow-[0_0_15px_rgba(124,58,237,0.5)]">
            <BookOpen className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className={`text-xl font-bold tracking-tight bg-gradient-to-r bg-clip-text text-transparent ${
              theme === 'dark' ? 'from-white to-slate-300' : 'from-violet-700 to-indigo-700'
            }`}>
              FANZA Ultimate Manager
            </h1>
            <p className={`text-xs font-semibold ${theme === 'dark' ? 'text-slate-500' : 'text-slate-600'}`}>ローカルライブラリ管理</p>
          </div>
        </div>

        {/* コントロール群 */}
        <div className="flex items-center gap-3">
          {/* 同期ステータス表示 */}
          {syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed' && (
            <div className={`flex items-center gap-3 px-4 py-2 rounded-xl text-xs font-semibold ${theme === 'dark' ? 'bg-violet-950/30 border border-violet-800/30' : 'bg-violet-50 border border-violet-200'}`}>
              <Loader className="w-3.5 h-3.5 animate-spin text-violet-500" />
              <div className="flex flex-col">
                <span>同期中 ({syncStatus.current}/{syncStatus.total})</span>
                <span className="text-[10px] opacity-70 truncate max-w-[150px]">{syncStatus.message}</span>
              </div>
            </div>
          )}

          {/* クイック同期ボタン */}
          <button 
            onClick={() => handleStartSync('quick')}
            disabled={syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed'}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-xl transition-all bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md hover:from-violet-500 hover:to-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-0.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed' ? 'animate-spin' : ''}`} />
            クイック同期
          </button>

          {/* フル同期ボタン */}
          <button 
            onClick={() => handleStartSync('full')}
            disabled={syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed'}
            className={`flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-xl border transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-0.5 ${theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'}`}
          >
            フル同期
          </button>

          {/* 修復同期ボタン */}
          <button 
            onClick={() => handleStartSync('repair')}
            disabled={syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed'}
            className={`flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-xl border transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:-translate-y-0.5 ${theme === 'dark' ? 'border-amber-800/30 hover:bg-amber-950/20 text-amber-400' : 'border-amber-200 hover:bg-amber-50 text-amber-700'}`}
          >
            <Wrench className="w-3.5 h-3.5" />
            修復同期
          </button>

          <div className="h-6 w-[1px] bg-slate-700/30"></div>

          {/* ログイン状態バッジ */}
          <div 
            onClick={() => setShowLoginModal(true)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition-all hover:-translate-y-0.5 cursor-pointer ${
              sessionStatus.authenticated
                ? theme === 'dark' ? 'bg-emerald-950/20 border-emerald-800/30 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : sessionStatus.status === 'EXPIRED'
                ? 'bg-rose-600/10 text-rose-500 border border-rose-500/20 animate-pulse'
                : theme === 'dark' ? 'bg-slate-800/50 border-white/5 text-slate-400' : 'bg-slate-100 border-slate-200 text-slate-600'
            }`}
            title={sessionStatus.authenticated ? 'ログイン中。クリックして再ログイン設定' : 'ログインされていません。クリックしてログイン設定'}
          >
            <span className={`w-2 h-2 rounded-full ${
              sessionStatus.authenticated ? 'bg-emerald-500' : sessionStatus.status === 'EXPIRED' ? 'bg-rose-500 animate-ping' : 'bg-slate-400'
            }`} />
            {sessionStatus.message}
          </div>

          {/* ログイン設定ボタン */}
          <button 
            onClick={() => setShowLoginModal(true)}
            className={`p-2.5 rounded-xl border transition-all hover:-translate-y-0.5 ${theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'}`}
            title="DMMログイン設定"
          >
            <User className="w-4 h-4" />
          </button>

          {/* アプリ設定ボタン */}
          <button 
            onClick={() => setShowSettingsModal(true)}
            className={`p-2.5 rounded-xl border transition-all hover:-translate-y-0.5 ${theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'}`}
            title="アプリ設定"
          >
            <Settings className="w-4 h-4" />
          </button>

          {/* システムログボタン */}
          <button 
            onClick={() => window.open('/logs.html', 'SystemLogs', 'width=900,height=600,resizable=yes,scrollbars=yes')}
            className={`p-2.5 rounded-xl border transition-all hover:-translate-y-0.5 ${theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'}`}
            title="システムログモニター"
          >
            <Terminal className="w-4 h-4" />
          </button>

          {/* テーマ切替トグル */}
          <button 
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className={`p-2.5 rounded-xl border transition-all hover:-translate-y-0.5 ${theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-yellow-400' : 'border-slate-200 hover:bg-slate-50 text-violet-600'}`}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </header>

      {/* メインレイアウト */}
      <main className="max-w-7xl mx-auto px-6 py-8 flex flex-col gap-6">

        {/* リアルタイム同期プログレスバー (同期処理中のみ表示) */}
        {syncStatus.status !== 'idle' && syncStatus.status !== 'complete' && syncStatus.status !== 'failed' && (
          <div className={`p-5 rounded-2xl border backdrop-blur-md shadow-lg ${theme === 'dark' ? 'bg-[#121420]/80 border-violet-500/20' : 'bg-white border-violet-100'}`}>
            <div className="flex justify-between items-center mb-3">
              <span className="text-xs font-bold text-violet-500 flex items-center gap-1.5 animate-pulse">
                <Loader className="w-3.5 h-3.5 animate-spin" />
                DMMライブラリと同期処理中...
              </span>
              <span className="text-xs font-semibold">{syncStatus.current} / {syncStatus.total} ({syncStatus.total > 0 ? Math.round((syncStatus.current / syncStatus.total) * 100) : 0}%)</span>
            </div>
            
            {/* プログレスバー本体 */}
            <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden mb-4 border border-white/5">
              <div 
                className="bg-gradient-to-r from-violet-600 via-fuchsia-500 to-indigo-500 h-full rounded-full transition-all duration-300"
                style={{ width: `${syncStatus.total > 0 ? (syncStatus.current / syncStatus.total) * 100 : 0}%` }}
              ></div>
            </div>

            <div className={`text-xs p-3 rounded-lg font-mono overflow-y-auto max-h-[80px] flex flex-col gap-1 border ${theme === 'dark' ? 'bg-[#07080f] border-white/5 text-slate-400' : 'bg-slate-50 border-slate-100 text-slate-600'}`}>
              {syncLogs.length > 0 ? (
                syncLogs.map((log, i) => (
                  <div key={i} className={`truncate shrink-0 ${i === 0 ? 'text-violet-400 font-bold' : 'opacity-70'}`}>
                    &gt; {log}
                  </div>
                ))
              ) : (
                <div className="opacity-50 shrink-0">&gt; ログ待機中...</div>
              )}
            </div>
          </div>
        )}

        {/* 検索・フィルター・ソートバー */}
        <section className={`p-5 rounded-2xl border flex flex-col gap-4 shadow-sm ${theme === 'dark' ? 'bg-[#0f111a] border-white/5' : 'bg-white border-slate-100'}`}>
          <div className="flex flex-col md:flex-row gap-4">
            
            {/* 複合検索窓 */}
            <div className="relative flex-1">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input 
                type="text" 
                placeholder="キーワード、タグ、声優、サークル名で複合検索 (スペース区切り)" 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className={`w-full pl-10 pr-4 py-2.5 rounded-xl border text-sm transition-all focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}
              />
            </div>

            {/* ジャンル選択 */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold opacity-75">ジャンル:</span>
              <select 
                value={selectedGenre}
                onChange={(e) => setSelectedGenre(e.target.value)}
                className={`px-3 py-2.5 rounded-xl border text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-700'}`}
              >
                <option value="all">すべて</option>
                {genres.map(g => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </div>

            {/* マイリスト選択 */}
            {mylists.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold opacity-75">マイリスト:</span>
                <select 
                  value={selectedMylist}
                  onChange={(e) => setSelectedMylist(e.target.value)}
                  className={`px-3 py-2.5 rounded-xl border text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-700'}`}
                >
                  <option value="all">すべて</option>
                  {mylists.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            )}

            {/* ソートキー選択 */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold opacity-75">ソート:</span>
              <select 
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value)}
                className={`px-3 py-2.5 rounded-xl border text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-700'}`}
              >
                <option value="purchase_date">購入日</option>
                <option value="price">価格</option>
                <option value="title">タイトル</option>
                <option value="last_updated">更新日時</option>
              </select>
              
              <button 
                onClick={() => setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')}
                className={`p-2.5 rounded-xl border transition-all text-xs font-bold ${theme === 'dark' ? 'border-white/10 hover:bg-white/5' : 'border-slate-200 hover:bg-slate-50'}`}
              >
                {sortDirection === 'asc' ? '昇順' : '降順'}
              </button>
            </div>

          </div>

          <div className="flex flex-wrap items-center gap-6 pt-2 border-t border-slate-700/10">
            
            {/* ストリーミング対応のみ表示 */}
            <label className="flex items-center gap-2.5 cursor-pointer text-xs font-bold select-none">
              <input 
                type="checkbox" 
                checked={showStreamingOnly}
                onChange={(e) => setShowStreamingOnly(e.target.checked)}
                className="w-4 h-4 rounded text-violet-600 focus:ring-violet-500/50"
              />
              ブラウザ再生対応のみ
            </label>

            {/* ダウンロード状態フィルタ */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold opacity-75">ダウンロード状況:</span>
              <div className="flex rounded-lg overflow-hidden border border-slate-700/20 text-xs">
                {(['all', 'downloaded', 'not_downloaded'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => setDownloadStatusFilter(mode)}
                    className={`px-3 py-1.5 font-semibold transition-all ${
                      downloadStatusFilter === mode 
                        ? 'bg-violet-600 text-white' 
                        : theme === 'dark' ? 'bg-[#161824] hover:bg-white/5' : 'bg-slate-50 hover:bg-slate-100'
                    }`}
                  >
                    {mode === 'all' ? 'すべて' : mode === 'downloaded' ? 'DL済み' : '未DL'}
                  </button>
                ))}
              </div>
            </div>

          </div>
        </section>

        {/* 作品一覧カードグリッド */}
        <section>
          {works.length === 0 ? (
            <div className={`p-16 rounded-2xl border text-center flex flex-col items-center gap-4 ${theme === 'dark' ? 'bg-[#0f111a] border-white/5' : 'bg-white border-slate-100'}`}>
              <AlertCircle className="w-12 h-12 text-slate-500" />
              <div>
                <h3 className="text-lg font-bold">作品が見つかりません</h3>
                <p className="text-sm opacity-60 mt-1">検索条件を変更するか、DMMライブラリと同期を行ってください。</p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-6">
              {works.map(work => (
                <div 
                  key={work.id}
                  onClick={() => loadWorkDetail(work.id)}
                  className={`group rounded-2xl border overflow-hidden cursor-pointer transition-all duration-300 hover:-translate-y-1.5 shadow-sm hover:shadow-xl flex flex-col ${
                    theme === 'dark' 
                      ? 'bg-[#0f111a]/90 border-white/5 hover:border-violet-500/30 shadow-black/20' 
                      : 'bg-white border-slate-150 hover:border-violet-200 shadow-slate-200'
                  }`}
                >
                  
                  {/* サムネイル画像 */}
                  <div className="relative aspect-[3/4] bg-slate-800 overflow-hidden">
                    {work.main_image ? (
                      <img 
                        src={`/api/proxy/image?url=${encodeURIComponent(work.main_image)}`} 
                        alt={work.title}
                        loading="lazy"
                        className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                      />
                    ) : (
                      <div className="w-full h-full bg-gradient-to-tr from-slate-900 via-indigo-950 to-slate-900 flex items-center justify-center text-[10px] text-slate-500 p-4 text-center">
                        画像なし
                      </div>
                    )}

                    {/* バッジ表示 */}
                    <div className="absolute top-2.5 left-2.5 flex flex-col gap-1.5">
                      {work.local_path && (
                        <span className="bg-emerald-600/90 text-white text-[10px] font-bold px-2 py-0.5 rounded-md flex items-center gap-1 shadow-md">
                          <CheckCircle className="w-2.5 h-2.5" />
                          DL済
                        </span>
                      )}
                      {work.is_streaming && (
                        <span className="bg-sky-600/90 text-white text-[10px] font-bold px-2 py-0.5 rounded-md flex items-center gap-1 shadow-md">
                          <Play className="w-2.5 h-2.5 fill-current" />
                          再生可
                        </span>
                      )}
                    </div>
                  </div>

                  {/* 作品テキスト情報 */}
                  <div className="p-4 flex flex-col flex-1 gap-2.5">
                    <span className="text-[10px] font-bold text-violet-500 tracking-wider uppercase truncate">{work.circle}</span>
                    <h3 className={`text-xs font-bold line-clamp-2 leading-relaxed flex-1 ${theme === 'dark' ? 'text-white' : 'text-slate-800'}`}>
                      {work.title}
                    </h3>
                    
                    <div className="flex justify-between items-center pt-2 border-t border-slate-700/10 text-[10px] font-semibold">
                      <span className="opacity-60">{work.purchase_date}</span>
                      <div className="text-[10px] font-semibold text-right">
                        {work.purchase_price !== null && work.purchase_price !== undefined ? (
                          <span className="text-emerald-500 font-bold">購入: {work.purchase_price.toLocaleString()}円</span>
                        ) : work.campaign_text && work.sale_price ? (
                          <div className="flex flex-col items-end leading-none gap-0.5">
                            <span className="text-[8px] px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-500 font-bold">{work.campaign_text}</span>
                            <span className="text-rose-500 font-bold">{work.sale_price.toLocaleString()}円</span>
                            {work.list_price > 0 && work.list_price !== work.sale_price && (
                              <span className="text-slate-500 line-through scale-90 origin-right">{work.list_price.toLocaleString()}円</span>
                            )}
                          </div>
                        ) : work.list_price > 0 ? (
                          <span className="text-amber-500">{work.list_price.toLocaleString()}円</span>
                        ) : work.price > 0 ? (
                          <span className="text-amber-500">{work.price.toLocaleString()}円</span>
                        ) : (
                          <span className="text-emerald-500">無料</span>
                        )}
                      </div>
                    </div>
                  </div>

                </div>
              ))}
            </div>
          )}
        </section>

      </main>

      {/* ----------------- 作品詳細モーダル ----------------- */}
      {selectedWorkId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm transition-opacity duration-300">
          <div className={`relative w-full max-w-4xl max-h-[90vh] rounded-3xl border shadow-2xl flex flex-col overflow-hidden transition-all duration-300 ${
            theme === 'dark' ? 'bg-[#0f111a] border-white/10' : 'bg-white border-slate-200'
          }`}>
            
            {/* モーダルヘッダー */}
            <div className="flex justify-between items-center p-5 border-b border-slate-700/10">
              <span className="text-xs font-extrabold text-violet-500">作品詳細</span>
              <button 
                onClick={() => setSelectedWorkId(null)}
                className="p-1.5 rounded-lg hover:bg-slate-700/10 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* モーダルコンテンツ (詳細がロードされるまでローダーを表示) */}
            {!selectedWork ? (
              <div className="flex-1 flex flex-col items-center justify-center p-20 gap-3">
                <Loader className="w-8 h-8 animate-spin text-violet-500" />
                <span className="text-xs font-bold opacity-60">作品情報を読み込み中...</span>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto p-6 md:p-8 flex flex-col md:flex-row gap-8">
                
                {/* 左側：メイン画像、アクションボタン、サンプル画像 */}
                <div className="w-full md:w-1/3 flex flex-col gap-6">
                  
                  {/* メイン画像 */}
                  <div className="relative aspect-[3/4] rounded-2xl overflow-hidden shadow-lg border border-slate-700/10 bg-slate-800">
                    {selectedWork.main_image ? (
                      <img src={`/api/proxy/image?url=${encodeURIComponent(selectedWork.main_image)}`} alt={selectedWork.title} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-slate-500">画像なし</div>
                    )}
                  </div>

                  {/* アクションボタン */}
                  <div className="flex flex-col gap-3">
                    
                    {/* 再生/マイライブラリで開く (メインアクション) */}
                    {selectedWork.local_path ? (
                      <>
                        <button 
                          onClick={() => setShowPlayerModal(true)}
                          className="w-full py-3 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-xl font-bold text-sm shadow-lg hover:from-emerald-500 hover:to-teal-500 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5"
                        >
                          <Play className="w-4 h-4 fill-current" />
                          ローカルファイル再生
                        </button>
                        
                        <div className={`p-3 rounded-xl border text-center text-xs font-semibold flex items-center justify-center gap-1.5 ${
                          theme === 'dark' ? 'bg-emerald-950/20 border-emerald-800/30 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                        }`}>
                          <CheckCircle className="w-4 h-4" />
                          ダウンロード済み
                        </div>

                        <a 
                          href={`https://www.dmm.co.jp/dc/-/mylibrary/detail/=/product_id=${selectedWork.id}/`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`w-full py-3 border text-center rounded-xl font-bold text-xs transition-all flex items-center justify-center gap-1.5 hover:-translate-y-0.5 ${
                            theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                          }`}
                        >
                          マイライブラリで開く
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      </>
                    ) : (
                      <>
                        <a 
                          href={`https://www.dmm.co.jp/dc/-/mylibrary/detail/=/product_id=${selectedWork.id}/`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="w-full py-3 bg-gradient-to-r from-violet-600 to-indigo-600 text-white rounded-xl font-bold text-sm shadow-lg hover:from-violet-500 hover:to-indigo-500 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5 text-center"
                        >
                          <ExternalLink className="w-4 h-4 inline-block mr-1 align-middle" />
                          マイライブラリで開く
                        </a>

                        <div className="flex flex-col gap-1.5">
                          <button 
                            onClick={() => handleDownload(selectedWork.id)}
                            disabled={downloadProgresses[selectedWork.id]?.status === 'DOWNLOADING'}
                            className="w-full py-3 bg-slate-800 hover:bg-slate-700 text-white rounded-xl font-bold text-sm border border-white/5 transition-all flex items-center justify-center gap-2 hover:-translate-y-0.5 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            {downloadProgresses[selectedWork.id]?.status === 'DOWNLOADING' ? (
                              <>
                                <Loader className="w-4 h-4 animate-spin" />
                                ダウンロード中 ({downloadProgresses[selectedWork.id]?.percent}%)
                              </>
                            ) : (
                              <>
                                <Download className="w-4 h-4" />
                                サーバーで自動ダウンロード
                              </>
                            )}
                          </button>
                          
                          <a 
                            href={`https://www.dmm.co.jp/dc/-/proxy/=/transfer_type=download/shop=doujin/product_id=${selectedWork.id}/`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`w-full py-3 border text-center rounded-xl font-bold text-xs transition-all flex items-center justify-center gap-1.5 hover:-translate-y-0.5 ${
                              theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                            }`}
                          >
                            ブラウザで直接ダウンロード
                            <ExternalLink className="w-3 h-3" />
                          </a>

                          {/* 個別ダウンロードのプログレス表示 */}
                          {downloadProgresses[selectedWork.id] && 
                           downloadProgresses[selectedWork.id].status !== 'IDLE' && 
                           !(downloadProgresses[selectedWork.id].status === 'COMPLETED' && !selectedWork.local_path) && (
                            <div className="w-full mt-1.5">
                              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                                <div 
                                  className="bg-emerald-500 h-full rounded-full transition-all duration-300"
                                  style={{ width: `${downloadProgresses[selectedWork.id].percent}%` }}
                                ></div>
                              </div>
                              <span className="text-[10px] text-slate-500 mt-1 block truncate">
                                {downloadProgresses[selectedWork.id].message}
                              </span>
                            </div>
                          )}
                        </div>
                      </>
                    )}

                    {/* 公式リンク */}
                    <a 
                      href={`https://www.dmm.co.jp/dc/doujin/-/detail/=/cid=${selectedWork.id}/`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`w-full py-3 border text-center rounded-xl font-bold text-xs transition-all flex items-center justify-center gap-1.5 hover:-translate-y-0.5 ${
                        theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-white' : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                      }`}
                    >
                      公式商品ページ
                      <ExternalLink className="w-3 h-3" />
                    </a>

                  </div>

                </div>

                {/* 右側：タイトル、詳細メタデータ、あらすじ、スペック表 */}
                <div className="flex-1 flex flex-col gap-6">
                  
                  {/* タイトルセクション */}
                  <div className="flex flex-col gap-2">
                    <span className="text-xs font-bold text-violet-500">{selectedWork.circle}</span>
                    <h2 className={`text-xl font-extrabold leading-snug ${theme === 'dark' ? 'text-white' : 'text-slate-800'}`}>
                      {selectedWork.title}
                    </h2>
                    <div className="flex flex-wrap items-center gap-3 mt-1.5 text-xs">
                      <span className="px-2.5 py-1 rounded-md bg-slate-800 text-slate-400 font-semibold">{selectedWork.genre}</span>
                      <span className="flex items-center gap-1 opacity-70"><Calendar className="w-3.5 h-3.5" />{selectedWork.purchase_date}</span>
                      
                      {/* 価格情報の詳細表示 */}
                      {selectedWork.list_price > 0 ? (
                        <span className="flex items-center gap-1 text-amber-500 font-semibold">
                          <DollarSign className="w-3.5 h-3.5" />
                          定価: {selectedWork.list_price.toLocaleString()}円
                          {selectedWork.campaign_text && selectedWork.sale_price && selectedWork.sale_price < selectedWork.list_price && (
                            <span className="text-rose-500 font-bold ml-1.5 bg-rose-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
                              <span className="text-[10px] bg-rose-500 text-white px-1 py-px rounded">{selectedWork.campaign_text}</span>
                              {selectedWork.sale_price.toLocaleString()}円
                            </span>
                          )}
                        </span>
                      ) : selectedWork.price > 0 ? (
                        <span className="flex items-center gap-1 text-amber-500 font-semibold">
                          <DollarSign className="w-3.5 h-3.5" />
                          {selectedWork.price.toLocaleString()}円
                        </span>
                      ) : (
                        <span className="text-emerald-500 font-semibold flex items-center gap-0.5">
                          <DollarSign className="w-3.5 h-3.5" />
                          無料
                        </span>
                      )}

                      {/* 購入価格の手動登録・編集 */}
                      <div className={`flex items-center gap-2 border-l pl-3 ${theme === 'dark' ? 'border-white/10' : 'border-slate-300/50'}`}>
                        <span className="opacity-70">購入価格:</span>
                        {isEditingPrice ? (
                          <div className="flex items-center gap-1.5">
                            <input 
                              type="text" 
                              placeholder="金額(円)" 
                              value={editingPurchasePrice}
                              onChange={(e) => setEditingPurchasePrice(e.target.value.replace(/[^\d]/g, ''))}
                              className={`w-20 px-2 py-0.5 rounded border text-xs focus:outline-none focus:ring-1 focus:ring-violet-500 ${
                                theme === 'dark' ? 'bg-[#161824] border-white/10 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'
                              }`}
                            />
                            <button 
                              onClick={() => handleSavePurchasePrice(selectedWork.id)}
                              className="px-2 py-0.5 bg-violet-600 hover:bg-violet-500 text-white text-[10px] font-bold rounded transition-all"
                            >
                              保存
                            </button>
                            <button 
                              onClick={() => {
                                setEditingPurchasePrice(selectedWork.purchase_price !== null ? selectedWork.purchase_price.toString() : '');
                                setIsEditingPrice(false);
                              }}
                              className="px-2 py-0.5 bg-slate-500 hover:bg-slate-400 text-white text-[10px] font-bold rounded transition-all"
                            >
                              戻る
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5">
                            <span className="text-emerald-500 font-bold">
                              {selectedWork.purchase_price !== null ? `${selectedWork.purchase_price.toLocaleString()}円` : '未記録'}
                            </span>
                            <button 
                              onClick={() => setIsEditingPrice(true)}
                              className={`px-2 py-0.5 border rounded text-[10px] font-semibold transition-all ${
                                theme === 'dark' ? 'border-white/10 hover:bg-white/5 text-slate-300' : 'border-slate-200 hover:bg-slate-50 text-slate-600'
                              }`}
                            >
                              記録
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* タグ一覧 */}
                  {selectedWork.specifications && (selectedWork.specifications['ジャンル'] || selectedWork.specifications['タグ']) && (
                    <div className="flex flex-col gap-2">
                      <h4 className="text-xs font-bold opacity-80 uppercase tracking-wider">タグ</h4>
                      <div className="flex flex-wrap gap-2">
                        {(selectedWork.specifications['ジャンル'] || selectedWork.specifications['タグ'])
                          .split(',')
                          .map(t => t.trim())
                          .filter(t => t.length > 0)
                          .map(tag => (
                            <button
                              key={tag}
                              onClick={() => {
                                setSelectedGenre('all');
                                setSelectedMylist('all');
                                setSearchQuery(tag);
                                setSelectedWorkId(null);
                              }}
                              className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition-all hover:-translate-y-0.5 ${
                                theme === 'dark'
                                  ? 'bg-violet-950/20 border-violet-800/30 text-violet-400 hover:bg-violet-900/30'
                                  : 'bg-violet-50 border-violet-200 text-violet-700 hover:bg-violet-100'
                              }`}
                            >
                              #{tag}
                            </button>
                          ))
                        }
                      </div>
                    </div>
                  )}

                  {/* あらすじ */}
                  {selectedWork.description && (
                    <div className="flex flex-col gap-2">
                      <h4 className="text-xs font-bold opacity-80 uppercase tracking-wider">あらすじ</h4>
                      <p className={`text-xs leading-relaxed whitespace-pre-line p-4 rounded-2xl ${
                        theme === 'dark' ? 'bg-[#151724]/60 border border-white/5 text-slate-300' : 'bg-slate-50 border border-slate-100 text-slate-600'
                      }`}>
                        {selectedWork.description}
                      </p>
                    </div>
                  )}

                  {/* サンプル画像カルーセル */}
                  {selectedWork.sample_images && selectedWork.sample_images.length > 0 && (
                    <div className="flex flex-col gap-2">
                      <h4 className="text-xs font-bold opacity-80 uppercase tracking-wider">サンプル画像</h4>
                      <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
                        {selectedWork.sample_images.map((src, i) => (
                          <div 
                            key={i}
                            onClick={() => window.open(`/api/proxy/image?url=${encodeURIComponent(src)}`, '_blank')}
                            className="relative flex-shrink-0 w-32 aspect-[3/4] rounded-xl overflow-hidden cursor-zoom-in border border-slate-700/20 bg-slate-800"
                          >
                            <img src={`/api/proxy/image?url=${encodeURIComponent(src)}`} alt={`サンプル ${i+1}`} className="w-full h-full object-cover" />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* スペックテーブル */}
                  {selectedWork.specifications && Object.keys(selectedWork.specifications).length > 0 && (
                    <div className="flex flex-col gap-2">
                      <h4 className="text-xs font-bold opacity-80 uppercase tracking-wider">詳細スペック</h4>
                      <div className={`border rounded-2xl overflow-hidden ${
                        theme === 'dark' ? 'border-white/5 bg-[#151724]/40' : 'border-slate-100 bg-white shadow-sm'
                      }`}>
                        <table className="w-full text-xs text-left border-collapse">
                          <tbody>
                            {Object.entries(selectedWork.specifications).map(([k, v], i) => (
                              <tr key={k} className={`border-b ${
                                theme === 'dark' ? 'border-white/5 hover:bg-white/5' : 'border-slate-50 hover:bg-slate-50'
                              } ${i % 2 === 0 ? '' : theme === 'dark' ? 'bg-white/5' : 'bg-slate-50/50'}`}>
                                <td className="px-4 py-3 font-bold opacity-80 w-1/3 border-r border-slate-700/10">{k}</td>
                                <td className="px-4 py-3 font-medium">{v}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                </div>

              </div>
            )}
          </div>
        </div>
      )}

      {/* ----------------- 再生プレイヤーモーダル ----------------- */}
      {showPlayerModal && selectedWork && (
        <PlayerModal 
          work={selectedWork} 
          theme={theme}
          onClose={() => setShowPlayerModal(false)} 
        />
      )}

      {/* ----------------- アプリ設定モーダル ----------------- */}
      {showSettingsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
          <div className={`w-full max-w-md p-6 rounded-3xl border shadow-2xl flex flex-col gap-6 relative ${
            theme === 'dark' ? 'bg-[#0f111a] border-white/10' : 'bg-white border-slate-200'
          }`}>
            <button onClick={() => setShowSettingsModal(false)} className="absolute top-4 right-4 p-1.5 rounded-lg hover:bg-slate-700/10 transition-colors">
              <X className="w-5 h-5" />
            </button>

            <div>
              <h3 className="text-lg font-bold">アプリ設定</h3>
              <p className="text-xs opacity-60 mt-1">保存先ディレクトリ等の管理設定です。</p>
            </div>

            <form onSubmit={handleSaveSettings} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold uppercase opacity-70">保存先フォルダパス</label>
                <div className="flex gap-2">
                  <input 
                    type="text" 
                    placeholder="C:\downloads" 
                    required
                    value={downloadDir}
                    onChange={(e) => setDownloadDir(e.target.value)}
                    className={`flex-1 px-4 py-2.5 rounded-xl border text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}
                  />
                  <button
                    type="button"
                    onClick={handleSelectDirectory}
                    className={`px-4 py-2.5 rounded-xl border text-xs font-bold transition-all hover:bg-slate-700/10 ${
                      theme === 'dark' ? 'border-white/10 text-white hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    参照...
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold uppercase opacity-70">ダウンロード容量の確認</label>
                <div className={`p-4 rounded-xl border text-sm flex items-center justify-between ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}>
                  <div>
                    <span className="font-bold">{downloadsInfo ? downloadsInfo.total_size_str : '0 MB'}</span>
                    <span className="text-[10px] opacity-60 block mt-0.5">ダウンロード済み: {downloadsInfo ? downloadsInfo.files.length : 0} 件</span>
                  </div>
                  {downloadsInfo && downloadsInfo.files.length > 0 && (
                    <button
                      type="button"
                      onClick={handleDeleteAllDownloads}
                      className="px-3 py-1.5 bg-rose-600/10 hover:bg-rose-600 text-rose-500 hover:text-white border border-rose-500/20 rounded-lg text-xs font-bold transition-all"
                    >
                      一括削除
                    </button>
                  )}
                </div>
              </div>

              <button 
                type="submit"
                className="w-full py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-xl font-bold text-sm shadow-md transition-all flex items-center justify-center gap-2"
              >
                設定を保存する
              </button>
            </form>

            <div className="border-t border-slate-700/10 pt-4 mt-2">
              <span className="text-xs font-bold text-rose-500 block mb-2">危険な操作</span>
              <button
                onClick={handleClearDatabase}
                className="w-full py-3 bg-rose-600/10 hover:bg-rose-600 text-rose-500 hover:text-white rounded-xl font-bold text-sm border border-rose-500/20 transition-all flex items-center justify-center gap-2"
              >
                データベースの全作品データを削除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ----------------- ログインモーダル ----------------- */}
      {showLoginModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
          <div className={`w-full max-w-md p-6 rounded-3xl border shadow-2xl flex flex-col gap-6 relative ${
            theme === 'dark' ? 'bg-[#0f111a] border-white/10' : 'bg-white border-slate-200'
          }`}>
            <button onClick={() => setShowLoginModal(false)} className="absolute top-4 right-4 p-1.5 rounded-lg hover:bg-slate-700/10 transition-colors">
              <X className="w-5 h-5" />
            </button>

            <div>
              <h3 className="text-lg font-bold">DMMログイン設定</h3>
              <p className="text-xs opacity-60 mt-1">Playwrightを使用してCookieを自動取得します。</p>
            </div>

            {authStatus.status === 'WAITING_FOR_2FA' ? (
              <form onSubmit={handle2FASubmit} className="flex flex-col gap-4">
                <div className={`p-4 rounded-2xl border text-xs font-semibold flex items-start gap-2.5 ${
                  theme === 'dark' ? 'bg-amber-950/20 border-amber-800/30 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-700'
                }`}>
                  <Lock className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <div>
                    二段階認証が必要です。
                    <span className="block font-medium opacity-85 mt-1">登録メールに送信されたコードを入力してください。</span>
                  </div>
                </div>
                
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold uppercase opacity-70">二段階認証コード (6桁)</label>
                  <input 
                    type="text" 
                    placeholder="123456" 
                    required
                    value={twoFactorCode}
                    onChange={(e) => setTwoFactorCode(e.target.value)}
                    className={`px-4 py-2.5 rounded-xl border text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}
                  />
                </div>

                <button 
                  type="submit"
                  className="w-full py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-xl font-bold text-sm shadow-md transition-all flex items-center justify-center gap-2"
                >
                  コードを送信する
                </button>
              </form>
            ) : (
              <form onSubmit={handleLoginSubmit} className="flex flex-col gap-4">
                {sessionStatus.status === 'EXPIRED' && (
                  <div className="text-xs text-rose-500 flex items-start gap-1.5 bg-rose-500/10 border border-rose-500/20 p-3 rounded-xl animate-pulse">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <div>
                      <span className="font-bold">セッションの期限が切れました。</span>
                      <span className="block opacity-85 mt-0.5">再度メールアドレスとパスワードを入力してログインしてください。</span>
                    </div>
                  </div>
                )}

                {/* ソーシャルログインガイド */}
                <div className={`p-4 rounded-2xl border text-xs leading-relaxed ${
                  theme === 'dark' ? 'bg-[#151724]/40 border-white/5 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-600'
                }`}>
                  <span className="font-bold block mb-1">💡 ソーシャルログイン（Google等）をご利用の場合</span>
                  メールアドレス欄を空のままログインボタンを押してください。立ち上がったブラウザ画面から手動でログインを完了すると、セッションが自動保存されます。
                </div>

                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold uppercase opacity-70">メールアドレス (自動入力用)</label>
                  <input 
                    type="email" 
                    placeholder="example@dmm.com" 
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={`px-4 py-2.5 rounded-xl border text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}
                  />
                </div>

                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold uppercase opacity-70">パスワード (自動入力用)</label>
                  <input 
                    type="password" 
                    placeholder="••••••••" 
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className={`px-4 py-2.5 rounded-xl border text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/50 ${theme === 'dark' ? 'bg-[#161824] border-white/5 text-white' : 'bg-slate-50 border-slate-200 text-slate-800'}`}
                  />
                </div>

                {authStatus.error_message && (
                  <div className="text-xs text-rose-500 flex items-start gap-1.5 bg-rose-500/10 border border-rose-500/20 p-3 rounded-xl">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{authStatus.error_message}</span>
                  </div>
                )}

                <button 
                  type="submit"
                  disabled={authStatus.status === 'LOGGING_IN'}
                  className="w-full py-3 bg-violet-600 hover:bg-violet-500 text-white rounded-xl font-bold text-sm shadow-md transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {authStatus.status === 'LOGGING_IN' ? (
                    <>
                      <Loader className="w-4 h-4 animate-spin" />
                      ログイン待機中...
                    </>
                  ) : email && password ? "自動ログインを開始" : "手動 / ソーシャルログインを開始"}
                </button>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
// ----------------- 動画・音声・コミック再生プレイヤーコンポーネント -----------------
interface PlayerModalProps {
  work: WorkDetail;
  theme: 'dark' | 'light';
  onClose: () => void;
}

function PlayerModal({ work, theme, onClose }: PlayerModalProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLVideoElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  
  const [isAudio, setIsAudio] = useState(false);
  const [isPdf, setIsPdf] = useState(false);
  
  // パッケージ内ファイルエクスプローラー用ステート
  const [zipFiles, setZipFiles] = useState<{name: string, size: number, type: string}[]>([]);
  const [selectedFile, setSelectedFile] = useState<{name: string, size: number, type: string} | null>(null);
  const [isLoadingFiles, setIsLoadingFiles] = useState(false);
  const [currentPath, setCurrentPath] = useState<string>("");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [showSidebar, setShowSidebar] = useState(true);
  const [showControls, setShowControls] = useState(true);
  
  // コミック画像スライドショー用ステート
  const [imageFiles, setImageFiles] = useState<{name: string, size: number, type: string}[]>([]);
  const [imageIndex, setImageIndex] = useState(0);

  // フルスクリーン切り替えハンドラー
  const toggleFullscreen = async () => {
    if (!modalRef.current) return;
    try {
      if (!document.fullscreenElement) {
        await modalRef.current.requestFullscreen();
        setIsFullscreen(true);
      } else {
        await document.exitFullscreen();
        setIsFullscreen(false);
      }
    } catch (err) {
      console.error("フルスクリーン切り替え失敗", err);
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
    };
  }, []);

  // 現在のディレクトリ直下にあるファイル・フォルダを抽出
  const getItemsInCurrentPath = () => {
    const itemsMap = new Map<string, { name: string; isDir: boolean; size?: number; type?: string; fileRef?: any }>();
    
    zipFiles.forEach(file => {
      const relativePath = currentPath 
        ? (file.name.startsWith(currentPath + '/') ? file.name.substring(currentPath.length + 1) : null)
        : file.name;
        
      if (relativePath === null) return;
      
      const parts = relativePath.split('/');
      if (parts.length === 1) {
        // 直下のファイル
        itemsMap.set(file.name, {
          name: parts[0],
          isDir: false,
          size: file.size,
          type: file.type,
          fileRef: file
        });
      } else if (parts.length > 1) {
        // 直下のフォルダ
        const dirName = parts[0];
        const fullDirName = currentPath ? `${currentPath}/${dirName}` : dirName;
        if (!itemsMap.has(fullDirName)) {
          itemsMap.set(fullDirName, {
            name: dirName,
            isDir: true
          });
        }
      }
    });
    
    return Array.from(itemsMap.values()).sort((a, b) => {
      // フォルダを優先し名前順でソート
      if (a.isDir && !b.isDir) return -1;
      if (!a.isDir && b.isDir) return 1;
      return a.name.localeCompare(b.name);
    });
  };

  const handleItemClick = (item: { name: string; isDir: boolean; fileRef?: any }) => {
    if (item.isDir) {
      const nextPath = currentPath ? `${currentPath}/${item.name}` : item.name;
      setCurrentPath(nextPath);
    } else if (item.fileRef) {
      selectFile(item.fileRef);
    }
  };

  const handleBackClick = () => {
    if (!currentPath) return;
    const parts = currentPath.split('/');
    parts.pop();
    setCurrentPath(parts.join('/'));
  };

  // ファイル配信エンドポイントのURL生成ヘルパー関数
  const getFileServeUrl = (file: {name: string}) => {
    return `/api/works/${work.id}/files/serve?path=${encodeURIComponent(file.name)}`;
  };

  // ファイル形式とジャンルの判別処理 (単一ファイル再生時のフォールバック用)
  useEffect(() => {
    const lowerPath = work.local_path?.toLowerCase() || '';
    const pdfDetect = lowerPath.endsWith('.pdf') || 
                      (work.specifications && Object.values(work.specifications).some(v => v.includes('PDF')));
    setIsPdf(pdfDetect);

    const soundDetect = work.genre === 'voice' || 
                        work.genre === 'voice_asmr' ||
                        work.genre === '音声' || 
                        work.title.includes('音声') || 
                        work.title.includes('ボイス') ||
                        (work.specifications && Object.values(work.specifications).some(v => v.includes('音声') || v.includes('MP3') || v.includes('Wav')));
    setIsAudio(soundDetect && !pdfDetect);
  }, [work]);

  // 収録ファイル一覧の取得処理
  useEffect(() => {
    if (work.id) {
      setIsLoadingFiles(true);
      fetch(`/api/works/${work.id}/files`)
        .then(res => {
          if (!res.ok) throw new Error();
          return res.json();
        })
        .then((data: {name: string, size: number, type: string}[]) => {
          // ファイルが取得できた場合にパッケージモードを有効化
          if (data && data.length > 0) {
            setZipFiles(data);
            
            const images = data.filter(f => f.type === 'image');
            setImageFiles(images);
            
            // デフォルトで再生するファイルを選択 (動画 -> 音声 -> PDF -> 画像の順に優先)
            const defaultPlayable = data.find(f => f.type === 'video') || 
                                    data.find(f => f.type === 'audio') || 
                                    data.find(f => f.type === 'pdf') || 
                                    data.find(f => f.type === 'image');
            if (defaultPlayable) {
              setSelectedFile(defaultPlayable);
              if (defaultPlayable.type === 'image') {
                const idx = images.findIndex(img => img.name === defaultPlayable.name);
                setImageIndex(idx >= 0 ? idx : 0);
                setShowSidebar(false);
              }
            }
          }
        })
        .catch(err => {
          console.error("パッケージ内のファイルリスト取得に失敗", err);
        })
        .finally(() => {
          setIsLoadingFiles(false);
        });
    }
  }, [work.id]);

  // 単一ファイル（非パッケージ）の再生制御処理 (動画・音声)
  useEffect(() => {
    if (zipFiles.length > 0 || isPdf) return;

    const mediaElement = isAudio ? audioRef.current : videoRef.current;
    if (!mediaElement) return;

    mediaElement.src = `/api/works/${work.id}/local-file`;
    mediaElement.load();
  }, [isAudio, zipFiles.length, isPdf, work.id]);

  // 画像スライドショーのキーボードページめくり処理
  useEffect(() => {
    if (zipFiles.length === 0 || !selectedFile || selectedFile.type !== 'image' || imageFiles.length === 0) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowLeft') {
        setImageIndex(prev => Math.max(0, prev - 1));
      } else if (e.key === 'ArrowRight' || e.key === ' ') {
        setImageIndex(prev => Math.min(imageFiles.length - 1, prev + 1));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [zipFiles.length, selectedFile, imageFiles, imageIndex]);

  const handlePrevPage = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setImageIndex(prev => Math.max(0, prev - 1));
  };

  const handleNextPage = (e?: React.MouseEvent) => {
    e?.stopPropagation();
    setImageIndex(prev => Math.min(imageFiles.length - 1, prev + 1));
  };

  const selectFile = (file: {name: string, size: number, type: string, online_url?: string, auth_key?: string}) => {
    setSelectedFile(file);
    setAutoPlay(true);
    if (file.type === 'image') {
      const idx = imageFiles.findIndex(img => img.name === file.name);
      setImageIndex(idx >= 0 ? idx : 0);
      setShowSidebar(false);
    } else {
      setShowSidebar(true);
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const isViewingImage = selectedFile?.type === 'image';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/95 backdrop-blur-md animate-fade-in">
      <div 
        ref={modalRef}
        className={`relative w-full shadow-2xl flex flex-col overflow-hidden transition-all duration-300 ${
          isFullscreen 
            ? 'w-screen h-screen rounded-none border-none p-0' 
            : `${zipFiles.length > 0 ? 'max-w-6xl h-[90vh]' : 'max-w-4xl'} rounded-3xl border`
        } ${
          theme === 'dark' ? 'bg-[#0a0b10] border-white/10' : 'bg-white border-slate-200'
        }`}
      >
        
        <div className={`flex justify-between items-center p-5 border-b z-30 transition-all duration-300 ${
          isViewingImage
            ? `absolute top-0 left-0 right-0 bg-black/75 border-none text-white backdrop-blur-sm ${
                showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'
              }`
            : `border-slate-700/10 bg-inherit ${theme === 'dark' ? 'text-white' : 'text-slate-800'}`
        }`}>
          <div className="flex items-center gap-2 text-xs font-bold text-violet-500">
            {isAudio ? <Volume2 className="w-4 h-4" /> : zipFiles.length > 0 || isPdf ? <BookOpen className="w-4 h-4" /> : <Play className="w-4 h-4 fill-current" />}
            <span className="truncate max-w-[300px] sm:max-w-[500px]">
              {work.title} 
              {zipFiles.length > 0 ? ' (パッケージエクスプローラー)' : isPdf ? ' (PDFビューアー)' : ' (ローカル再生)'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {isViewingImage && zipFiles.length > 0 && (
              <button
                onClick={() => setShowSidebar(!showSidebar)}
                className={`p-1.5 rounded-lg transition-colors ${theme === 'dark' ? 'hover:bg-white/5 text-slate-400 hover:text-slate-200' : 'hover:bg-slate-100 text-slate-400 hover:text-slate-700'}`}
                title={showSidebar ? "一覧を隠す" : "一覧を表示"}
              >
                <Folder className="w-5 h-5" />
              </button>
            )}
            <button
              onClick={toggleFullscreen}
              className={`p-1.5 rounded-lg transition-colors ${theme === 'dark' ? 'hover:bg-white/5 text-slate-400 hover:text-slate-200' : 'hover:bg-slate-100 text-slate-600 hover:text-slate-800'}`}
              title={isFullscreen ? "フルスクリーン解除" : "フルスクリーン"}
            >
              {isFullscreen ? <Minimize2 className="w-5 h-5" /> : <Maximize2 className="w-5 h-5" />}
            </button>
            <button 
              onClick={onClose}
              className={`p-1.5 rounded-lg transition-colors ${theme === 'dark' ? 'hover:bg-white/5 text-slate-400 hover:text-slate-200' : 'hover:bg-slate-100 text-slate-600 hover:text-slate-800'}`}
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 flex overflow-hidden min-h-0 bg-[#020205] relative">
          
          {zipFiles.length > 0 && (
            <div className={`${
              isViewingImage
                ? `absolute left-0 top-0 bottom-0 z-20 w-64 bg-[#08090d]/95 border-r border-white/10 transition-all duration-300 ${
                    showSidebar && showControls ? 'translate-x-0 opacity-100' : '-translate-x-full opacity-0 pointer-events-none'
                  }`
                : 'w-64 border-r border-slate-700/10 bg-[#08090d]/80 min-w-[200px]'
            } flex flex-col`}>
              <div className="p-4 border-b border-slate-700/10 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                エクスプローラー
              </div>
              
              {/* パンくずリスト */}
              <div className="px-4 py-2 border-b border-slate-700/10 flex items-center gap-1 text-[10px] overflow-x-auto whitespace-nowrap bg-slate-900/10 select-none">
                <button 
                  onClick={() => setCurrentPath("")}
                  className={`font-bold hover:underline ${!currentPath ? 'text-violet-500' : 'text-slate-400'}`}
                >
                  ルート
                </button>
                {currentPath.split('/').filter(Boolean).map((part, index, arr) => {
                  const pathSlice = arr.slice(0, index + 1).join('/');
                  return (
                    <React.Fragment key={pathSlice}>
                      <span className="opacity-40 text-slate-500">/</span>
                      <button 
                        onClick={() => setCurrentPath(pathSlice)}
                        className={`font-bold hover:underline ${index === arr.length - 1 ? 'text-violet-500' : 'text-slate-400'}`}
                      >
                        {part}
                      </button>
                    </React.Fragment>
                  );
                })}
              </div>

              <div className="flex-1 overflow-y-auto p-2 gap-1 flex flex-col scrollbar-thin">
                {isLoadingFiles ? (
                  <div className="flex-1 flex flex-col items-center justify-center gap-2 p-6">
                    <Loader className="w-5 h-5 animate-spin text-violet-500" />
                    <span className="text-[10px] text-slate-500">スキャン中...</span>
                  </div>
                ) : zipFiles.length === 0 ? (
                  <div className="p-4 text-[10px] text-slate-500">ファイルが見つかりません。</div>
                ) : (
                  <>
                    {/* 上の階層へ戻るボタン */}
                    {currentPath && (
                      <button
                        onClick={handleBackClick}
                        className="w-full text-left p-2.5 rounded-xl text-xs flex items-center gap-2 hover:bg-white/5 border border-transparent text-slate-400 hover:text-slate-200"
                      >
                        <span className="text-sm shrink-0">📁</span>
                        <span className="font-bold">.. (上の階層へ)</span>
                      </button>
                    )}

                    {getItemsInCurrentPath().map(item => {
                      const isSelected = !item.isDir && selectedFile?.name === item.fileRef?.name;
                      return (
                        <button
                          key={item.isDir ? `dir-${item.name}` : `file-${item.fileRef.name}`}
                          onClick={() => handleItemClick(item)}
                          className={`w-full text-left p-2.5 rounded-xl text-xs flex flex-col gap-1 transition-all ${
                            isSelected
                              ? 'bg-violet-600/20 text-violet-400 font-bold border border-violet-500/20'
                              : 'hover:bg-white/5 border border-transparent text-slate-400 hover:text-slate-200'
                          }`}
                        >
                          <div className="flex items-center gap-2 truncate">
                            <span className="text-sm shrink-0">
                              {item.isDir 
                                ? '📁' 
                                : item.type === 'video' ? '🎬' : item.type === 'audio' ? '🎵' : item.type === 'pdf' ? '📄' : item.type === 'image' ? '🖼️' : '📄'}
                            </span>
                            <span className="truncate" title={item.name}>
                              {item.name}
                            </span>
                          </div>
                          {!item.isDir && item.size !== undefined && (
                            <span className="text-[9px] opacity-60 pl-6">{formatSize(item.size)}</span>
                          )}
                        </button>
                      );
                    })}
                  </>
                )}
              </div>
            </div>
          )}

          <div className={`flex-1 flex flex-col justify-center items-center relative overflow-hidden bg-black transition-all duration-300 ${
            isViewingImage
              ? `w-full h-full z-10 ${showSidebar && showControls ? 'pl-64' : 'pl-0'}`
              : ''
          }`}>
            
            {zipFiles.length > 0 ? (
              selectedFile ? (
                selectedFile.type === 'video' ? (
                  <video 
                    key={selectedFile.name}
                    src={getFileServeUrl(selectedFile)}
                    controls 
                    autoPlay={autoPlay}
                    className="w-full h-full max-h-[85vh] object-contain"
                  />
                ) : selectedFile.type === 'audio' ? (
                  <div className="w-full h-full relative flex flex-col items-center justify-center p-8 overflow-hidden">
                    {work.main_image && (
                      <img 
                        src={`/api/proxy/image?url=${encodeURIComponent(work.main_image)}`} 
                        alt="" 
                        className="absolute inset-0 w-full h-full object-cover filter blur-2xl opacity-20 scale-110 select-none pointer-events-none" 
                      />
                    )}
                    <div className="relative w-40 aspect-[3/4] rounded-2xl overflow-hidden shadow-2xl border border-white/10 z-10 bg-slate-800 mb-6">
                      {work.main_image ? (
                        <img src={`/api/proxy/image?url=${encodeURIComponent(work.main_image)}`} alt={work.title} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-slate-500">画像なし</div>
                      )}
                    </div>
                    <div className="text-center max-w-lg z-10 px-4 mb-4">
                      <span className="text-[10px] font-bold text-violet-500 tracking-wider uppercase">再生中のトラック</span>
                      <h3 className="text-xs font-bold text-white line-clamp-2 mt-1 leading-snug">{selectedFile.name.split('/').pop()}</h3>
                    </div>
                    <audio 
                      key={selectedFile.name}
                      src={getFileServeUrl(selectedFile)}
                      controls 
                      autoPlay={autoPlay}
                      className="w-full max-w-md z-10 mt-2 filter invert dark:invert-0"
                    />
                  </div>
                ) : selectedFile.type === 'pdf' ? (
                  <iframe 
                    key={selectedFile.name}
                    src={getFileServeUrl(selectedFile)}
                    className="w-full h-full border-none"
                    title="PDFビューアー"
                  />
                ) : selectedFile.type === 'image' && imageFiles.length > 0 ? (
                  <div className="w-full h-full relative flex items-center justify-center select-none">
                    <div 
                      onClick={handlePrevPage}
                      className="absolute left-0 top-0 w-1/4 h-full z-20 cursor-w-resize group flex items-center justify-start pl-6"
                    >
                      <div className="bg-black/50 p-3 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
                        <X className="w-6 h-6 text-white rotate-90" />
                      </div>
                    </div>
                    
                    <div 
                      onClick={handleNextPage}
                      className="absolute right-0 top-0 w-1/4 h-full z-20 cursor-e-resize group flex items-center justify-end pr-6"
                    >
                      <div className="bg-black/50 p-3 rounded-full opacity-0 group-hover:opacity-100 transition-opacity">
                        <X className="w-6 h-6 text-white -rotate-90" />
                      </div>
                    </div>

                    <div 
                      onClick={() => setShowControls(!showControls)}
                      className="absolute left-1/4 w-1/2 h-full z-20 cursor-pointer bg-transparent"
                    />

                    <img 
                      src={getFileServeUrl(imageFiles[imageIndex])} 
                      alt={`ページ ${imageIndex + 1}`}
                      className="max-w-full max-h-full object-contain pointer-events-none z-10 transition-transform duration-200 shadow-2xl"
                    />
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3 text-slate-400 p-8">
                    <span className="text-3xl">📁</span>
                    <span className="text-xs font-bold">{selectedFile.name.split('/').pop()}</span>
                    <span className="text-[10px] opacity-70">このファイル形式のプレビューはサポートされていません。</span>
                  </div>
                )
              ) : (
                <div className="text-slate-500 text-xs">再生可能なメディアファイルを選択してください。</div>
              )
            ) : isPdf ? (
              <iframe 
                src={`/api/works/${work.id}/local-file`}
                className="w-full h-full border-none"
                title="PDFビューアー"
              />
            ) : isAudio ? (
              <div className="w-full h-full relative flex flex-col items-center justify-center p-8 overflow-hidden">
                {work.main_image && (
                  <img 
                    src={`/api/proxy/image?url=${encodeURIComponent(work.main_image)}`} 
                    alt="" 
                    className="absolute inset-0 w-full h-full object-cover filter blur-2xl opacity-20 scale-110 select-none pointer-events-none" 
                  />
                )}
                <div className="relative w-48 sm:w-60 aspect-[3/4] rounded-2xl overflow-hidden shadow-2xl border border-white/10 z-10 bg-slate-800 mb-6">
                  {work.main_image ? (
                    <img src={`/api/proxy/image?url=${encodeURIComponent(work.main_image)}`} alt={work.title} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-500">画像なし</div>
                  )}
                </div>
                <div className="text-center max-w-lg z-10 px-4 mb-4">
                  <span className="text-[10px] font-bold text-violet-500 tracking-wider uppercase">{work.circle}</span>
                  <h3 className="text-sm font-bold text-white line-clamp-2 mt-1 leading-snug">{work.title}</h3>
                </div>
                <audio 
                  ref={audioRef}
                  controls 
                  autoPlay={autoPlay}
                  className="w-full max-w-md z-10 mt-2 filter invert dark:invert-0"
                />
              </div>
            ) : (
              <video 
                ref={videoRef}
                controls 
                autoPlay={autoPlay}
                className="w-full h-full max-h-[70vh] object-contain"
              />
            )}

          </div>
        </div>

        <div className={`p-4 border-t z-30 flex justify-center items-center gap-4 text-xs font-bold transition-all duration-300 ${
          isViewingImage
            ? `absolute bottom-0 left-0 right-0 bg-black/75 border-none text-white backdrop-blur-sm ${
                showControls ? 'opacity-100' : 'opacity-0 pointer-events-none'
              }`
            : `border-slate-700/10 bg-inherit`
        }`}>
          {zipFiles.length > 0 && selectedFile && selectedFile.type === 'image' && imageFiles.length > 0 && (
            <div className="flex items-center gap-4">
              <button
                onClick={handlePrevPage}
                disabled={imageIndex === 0}
                className={`px-4 py-2 rounded-xl disabled:opacity-30 disabled:cursor-not-allowed transition-all ${
                  isViewingImage ? 'bg-white/10 hover:bg-white/20 text-white' : 'bg-slate-800 hover:bg-slate-700 text-white'
                }`}
              >
                前へ
              </button>
              <span className={`${isViewingImage ? 'text-slate-300' : 'text-slate-400'} font-mono`}>
                {imageIndex + 1} / {imageFiles.length} ページ
              </span>
              <button
                onClick={handleNextPage}
                disabled={imageIndex === imageFiles.length - 1}
                className={`px-4 py-2 rounded-xl disabled:opacity-30 disabled:cursor-not-allowed transition-all ${
                  isViewingImage ? 'bg-white/10 hover:bg-white/20 text-white' : 'bg-slate-800 hover:bg-slate-700 text-white'
                }`}
              >
                次へ
              </button>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
