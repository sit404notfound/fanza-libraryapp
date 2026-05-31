export interface Work {
  id: string; // 作品CID
  title: string; // 作品タイトル
  circle: string; // サークル名
  genre: string; // ジャンル
  is_unavailable: boolean; // 販売停止フラグ
  is_streaming: boolean; // ストリーミング対応フラグ
  purchase_date: string; // 購入日
  is_mylist_registered: boolean; // マイリスト登録フラグ
  main_image: string | null; // メイン画像URL
  price: number; // 価格 (現在の販売価格)
  list_price: number; // 定価 (サークル設定価格)
  sale_price: number | null; // セール価格 (割引適用後)
  purchase_price: number | null; // 購入価格 (手動記録)
  campaign_text: string | null; // セール情報テキスト (例: "80%OFF")
  local_path: string | null; // ローカル絶対パス
}

export interface WorkDetail extends Work {
  description: string; // あらすじ
  sample_images: string[]; // サンプル画像URL配列
  author: string[]; // 作者名配列
  specifications: Record<string, string>; // 詳細スペック辞書
  mylists: string[]; // 登録マイリスト名配列
}

export interface SyncStatus {
  status: 'idle' | 'start' | 'processing_list' | 'processing_detail' | 'complete' | 'failed' | 'error'; // 同期ステータス
  current: number; // 現在処理件数
  total: number; // 合計件数
  message: string; // 進捗詳細メッセージ
}

export interface AuthStatus {
  status: 'IDLE' | 'LOGGING_IN' | 'WAITING_FOR_2FA' | 'SUCCESS' | 'FAILED'; // ログインステータス
  error_message: string | null; // エラーメッセージ
}

export interface DownloadStatus {
  percent: number; // ダウンロードパーセント
  status: 'IDLE' | 'STARTING' | 'PREPARING' | 'DOWNLOADING' | 'SAVING' | 'COMPLETED' | 'FAILED'; // ダウンロードステータス
  message: string; // ダウンロード詳細メッセージ
}
