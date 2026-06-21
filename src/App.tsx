import { useEffect, useRef, useState } from 'react'
import { Plus, Trash2, Settings } from 'lucide-react'
import './App.css'

type Memo = {
  id: string
  title: string
  content: string
  created?: number // 作成日時（epoch 秒）
  updated?: number // 最終更新日時（epoch 秒）
}

// epoch 秒を「2026/06/20 11:27」形式に整形
function formatTime(sec?: number): string {
  if (!sec) return '—'
  const d = new Date(sec * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

type Theme = 'light' | 'dark'

type AppSettings = {
  theme: Theme
  titleSize: number
  contentSize: number
  listSize: number
}

const SETTINGS_KEY = 'jammemo-settings'

// 設定をローカルに読み込む（無ければ既定値。テーマは OS 設定に追従）
function loadSettings(): AppSettings {
  const defaults: AppSettings = {
    theme: window.matchMedia?.('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light',
    titleSize: 24,
    contentSize: 16,
    listSize: 16,
  }
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    if (raw) return { ...defaults, ...JSON.parse(raw) }
  } catch {
    /* 壊れていたら既定値 */
  }
  return defaults
}

// 配信パス配下の保存API (例: /~sugawara/jammemo/api.cgi)
const API = import.meta.env.BASE_URL + 'api.cgi'

// 新しいものが上に来るように id(=日付_連番) の降順で並べる
function sortDesc(memos: Memo[]): Memo[] {
  return [...memos].sort((a, b) => (a.id < b.id ? 1 : a.id > b.id ? -1 : 0))
}

async function apiList(): Promise<Memo[]> {
  const res = await fetch(API)
  if (!res.ok) throw new Error('一覧の取得に失敗しました')
  return res.json()
}

// 設定画面のフォントサイズ確認用サンプル（無ければサーバーが自動生成）
async function apiExample(): Promise<{
  title: string
  content: string
  created?: number
  updated?: number
}> {
  const res = await fetch(`${API}?example=1`)
  if (!res.ok) throw new Error('サンプルの取得に失敗しました')
  return res.json()
}

async function apiCreate(): Promise<Memo> {
  const res = await fetch(API, { method: 'POST' })
  if (!res.ok) throw new Error('作成に失敗しました')
  return res.json()
}

async function apiSave(memo: Memo): Promise<{ updated?: number }> {
  const res = await fetch(`${API}?id=${encodeURIComponent(memo.id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: memo.title, content: memo.content }),
  })
  if (!res.ok) throw new Error('保存に失敗しました')
  return res.json()
}

async function apiDelete(id: string): Promise<void> {
  const res = await fetch(`${API}?id=${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('削除に失敗しました')
}

function App() {
  const [memos, setMemos] = useState<Memo[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [status, setStatus] = useState<'saved' | 'saving' | 'error'>('saved')
  // 削除確認モーダルの対象メモID（null のとき非表示）
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  // 設定画面を右側に表示するか
  const [showSettings, setShowSettings] = useState(false)
  // 表示設定（テーマ・フォントサイズ）
  const [settings, setSettings] = useState<AppSettings>(loadSettings)
  // 設定プレビュー用サンプル
  const [example, setExample] = useState<{
    title: string
    content: string
    created?: number
    updated?: number
  } | null>(null)

  // 保存のデバウンス用タイマー（メモID単位）
  const saveTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})

  // 設定をDOMへ反映＆ローカルに保存
  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', settings.theme)
    root.style.setProperty('--title-size', `${settings.titleSize}px`)
    root.style.setProperty('--content-size', `${settings.contentSize}px`)
    root.style.setProperty('--list-size', `${settings.listSize}px`)
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
    } catch {
      /* 保存失敗は無視（プライベートモード等） */
    }
  }, [settings])

  // 初回ロード：サーバーから一覧取得。空なら空メモを1つ作る
  useEffect(() => {
    ;(async () => {
      try {
        let list = await apiList()
        if (list.length === 0) {
          list = [await apiCreate()]
        }
        list = sortDesc(list)
        setMemos(list)
        setSelectedId(list[0].id)
      } catch (e) {
        console.error(e)
        setStatus('error')
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  // プレビュー用サンプルを取得（取得失敗は致命的でないので無視）
  useEffect(() => {
    apiExample()
      .then(setExample)
      .catch((e) => console.error(e))
  }, [])

  const selected = memos.find((m) => m.id === selectedId) ?? null

  function scheduleSave(memo: Memo) {
    setStatus('saving')
    clearTimeout(saveTimers.current[memo.id])
    saveTimers.current[memo.id] = setTimeout(async () => {
      try {
        const r = await apiSave(memo)
        if (r.updated) {
          setMemos((prev) =>
            prev.map((m) =>
              m.id === memo.id ? { ...m, updated: r.updated } : m,
            ),
          )
        }
        setStatus('saved')
      } catch (e) {
        console.error(e)
        setStatus('error')
      }
    }, 500)
  }

  function updateSelected(patch: Partial<Memo>) {
    if (!selected) return
    const updated = { ...selected, ...patch }
    setMemos((prev) => prev.map((m) => (m.id === updated.id ? updated : m)))
    scheduleSave(updated)
  }

  async function addMemo() {
    try {
      const memo = await apiCreate()
      setMemos((prev) => sortDesc([memo, ...prev]))
      setSelectedId(memo.id)
      setShowSettings(false)
    } catch (e) {
      console.error(e)
      setStatus('error')
    }
  }

  async function deleteMemo(id: string) {
    try {
      await apiDelete(id)
      let next = memos.filter((m) => m.id !== id)
      // 全部消えたら空メモを1つ用意する
      if (next.length === 0) {
        next = [await apiCreate()]
      }
      next = sortDesc(next)
      setMemos(next)
      if (id === selectedId) setSelectedId(next[0].id)
    } catch (e) {
      console.error(e)
      setStatus('error')
    }
  }

  if (loading) {
    return <div className="loading">読み込み中…</div>
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-header">
          <h1 className="logo">
            <a href={import.meta.env.BASE_URL}>jam memo</a>
          </h1>
          <button type="button" className="add-button" onClick={addMemo}>
            <Plus size={16} />
            新規メモ
          </button>
        </div>
        <ul className="memo-list">
          {memos.map((memo) => (
            <li
              key={memo.id}
              className={
                'memo-item' +
                (memo.id === selectedId && !showSettings ? ' selected' : '')
              }
              onClick={() => {
                setSelectedId(memo.id)
                setShowSettings(false)
              }}
            >
              <span className="memo-item-title">
                {memo.title.trim() || '（無題）'}
              </span>
              <button
                type="button"
                className="delete-button"
                title="削除"
                onClick={(e) => {
                  e.stopPropagation()
                  setPendingDelete(memo.id)
                }}
              >
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
        <div className="status">
          <span className="status-text">
            {status === 'saving' && '保存中…'}
            {status === 'saved' && '保存済み'}
            {status === 'error' && '⚠ 保存エラー'}
          </span>
          <button
            type="button"
            className={'settings-button' + (showSettings ? ' active' : '')}
            title="設定"
            onClick={() => setShowSettings(true)}
          >
            <Settings size={16} />
          </button>
        </div>
      </aside>

      <main className="editor">
        {showSettings ? (
          <div className="settings-panel">
            <div className="settings-head">
              <h2 className="settings-title">設定</h2>
              <button
                type="button"
                className="settings-close"
                onClick={() => setShowSettings(false)}
              >
                閉じる
              </button>
            </div>

            <section className="settings-section">
              <h3 className="settings-label">テーマ</h3>
              <div className="theme-options">
                {(['light', 'dark'] as Theme[]).map((t) => (
                  <button
                    key={t}
                    type="button"
                    className={
                      'theme-option' + (settings.theme === t ? ' selected' : '')
                    }
                    onClick={() => setSettings((s) => ({ ...s, theme: t }))}
                  >
                    {t === 'light' ? 'ライトモード' : 'ダークモード'}
                  </button>
                ))}
              </div>
            </section>

            <section className="settings-section">
              <h3 className="settings-label">フォントサイズ</h3>
              {(
                [
                  ['titleSize', 'メモのタイトル（右）'],
                  ['contentSize', 'メモの本文（右）'],
                  ['listSize', 'メモ一覧（左）'],
                ] as [keyof AppSettings, string][]
              ).map(([key, label]) => (
                <div key={key} className="size-row">
                  <span className="size-row-label">{label}</span>
                  <input
                    type="range"
                    min={10}
                    max={40}
                    value={settings[key] as number}
                    onChange={(e) =>
                      setSettings((s) => ({
                        ...s,
                        [key]: Number(e.target.value),
                      }))
                    }
                  />
                  <span className="size-row-value">{settings[key]}px</span>
                </div>
              ))}

              {example && (
                <div className="settings-preview">
                  <div className="settings-preview-title">{example.title}</div>
                  <div className="editor-meta">
                    <span>作成: {formatTime(example.created)}</span>
                    <span>更新: {formatTime(example.updated)}</span>
                  </div>
                  <div className="settings-preview-content">
                    {example.content}
                  </div>
                </div>
              )}
            </section>
          </div>
        ) : (
          selected && (
            <>
              <input
                className="editor-title"
                type="text"
                placeholder="タイトル"
                value={selected.title}
                onChange={(e) => updateSelected({ title: e.target.value })}
              />
              <div className="editor-meta">
                <span>作成: {formatTime(selected.created)}</span>
                <span>更新: {formatTime(selected.updated)}</span>
              </div>
              <textarea
                className="editor-content"
                placeholder="内容を入力…"
                value={selected.content}
                onChange={(e) => updateSelected({ content: e.target.value })}
              />
            </>
          )
        )}
      </main>

      {pendingDelete && (
        <div className="modal-overlay" onClick={() => setPendingDelete(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-icon">
              <Trash2 size={28} />
            </div>
            <p className="modal-message">
              「
              {memos.find((m) => m.id === pendingDelete)?.title.trim() ||
                '（無題）'}
              」を本当に削除しますか？
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="modal-button cancel"
                onClick={() => setPendingDelete(null)}
              >
                キャンセル
              </button>
              <button
                type="button"
                className="modal-button ok"
                onClick={() => {
                  const id = pendingDelete
                  setPendingDelete(null)
                  deleteMemo(id)
                }}
              >
                削除する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
