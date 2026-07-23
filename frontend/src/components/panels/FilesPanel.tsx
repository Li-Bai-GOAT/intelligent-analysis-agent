import { useState, useEffect, useCallback } from 'react'
import * as XLSX from 'xlsx'
import mammoth from 'mammoth'
import JSZip from 'jszip'
import { Api } from '../../api/client'
import { useSessionStore } from '../../stores/session'
import { Folder, File, FileText, FileCode, FileSpreadsheet, Download, RefreshCw, ChevronRight, ArrowLeft, ExternalLink } from 'lucide-react'

interface FileItem {
  name: string
  path: string
  is_dir: boolean
  type?: string  // 后端返回 "file" | "directory"
  size?: number
}

// PDF 预览组件
function PdfViewer({ url, title }: { url: string; title: string }) {
  return (
    <iframe
      src={url}
      className="flex-1 w-full border-0 bg-white"
      title={`${title} preview`}
    />
  )
}

// PPT 幻灯片预览组件
function PptxViewer({ slides }: { slides: string[] }) {
  return (
    <div className="flex-1 overflow-auto p-3" style={{ background: '#1e1e2e' }}>
      {slides.map((text, i) => (
        <div key={i} className="mb-4 p-4 rounded-lg" style={{ background: '#313244', color: '#cdd6f4' }}>
          <div className="text-xs mb-2" style={{ color: '#a6adc8' }}>幻灯片 {i + 1}</div>
          <div className="whitespace-pre-wrap text-sm leading-relaxed">{text || '(空白幻灯片)'}</div>
        </div>
      ))}
      {slides.length === 0 && <p style={{ color: '#a6adc8' }}>无幻灯片内容</p>}
    </div>
  )
}

export function FilesPanel() {
  const currentSession = useSessionStore((s) => s.currentSession)
  const [files, setFiles] = useState<FileItem[]>([])
  const [currentPath, setCurrentPath] = useState('')
  const [fileContent, setFileContent] = useState<{ name: string; content: string; fullPath: string; isImage?: boolean; isHtml?: boolean; isExcel?: boolean; isWord?: boolean; isPdf?: boolean; isPptx?: boolean; pdfUrl?: string; pptxSlides?: string[]; excelData?: { headers: string[]; rows: (string | number)[][] } } | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)

  const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  }

  const downloadFile = async (path: string, filename: string) => {
    if (!currentSession) return
    saveBlob(await Api.downloadSandboxFile(currentSession, path), filename)
  }

  const downloadZip = async () => {
    if (!currentSession) return
    saveBlob(await Api.downloadSandboxZip(currentSession), `workspace_${currentSession.slice(0, 8)}.zip`)
  }

  const readBinaryFile = async (path: string) => {
    if (!currentSession) throw new Error('no session')
    const blob = await Api.downloadSandboxFile(currentSession, path)
    return new Uint8Array(await blob.arrayBuffer())
  }

  const openHtmlInNewPage = (html: string) => {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const opened = window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), opened ? 60_000 : 0)
  }

  const loadFiles = useCallback(async (path = '') => {
    if (!currentSession) return
    setLoading(true)
    try {
      const data = await Api.listSandboxWorkspace(currentSession, path)
      // 后端返回 type: "file" | "directory"，前端使用 is_dir: boolean
      const mapped = Array.isArray(data)
        ? data
            .filter(item => !item.name.toLowerCase().endsWith('.py'))
            .map(item => ({
              name: item.name,
              path: item.path,
              is_dir: item.is_dir ?? item.type === 'directory',
              size: item.size,
            }))
        : []
      setFiles(mapped)
      setCurrentPath(path)
      setFileContent(null)
    } catch {
      // 404 = sandbox not created yet, silently ignore
      setFiles([])
    } finally {
      setLoading(false)
    }
  }, [currentSession])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadFiles()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadFiles])

  useEffect(() => {
    const objectUrl = fileContent?.isImage || fileContent?.isPdf ? fileContent.content : null
    return () => {
      if (objectUrl?.startsWith('blob:')) URL.revokeObjectURL(objectUrl)
    }
  }, [fileContent?.content, fileContent?.isImage, fileContent?.isPdf])

  const viewFile = async (fullPath: string, name: string) => {
    if (!currentSession) return
    const ext = name.split('.').pop()?.toLowerCase()
    const isHtml = ext === 'html' || ext === 'htm'
    const isExcel = ext === 'xlsx' || ext === 'xls' || ext === 'csv'
    const isWord = ext === 'docx' || ext === 'doc'
    const isPdf = ext === 'pdf'
    const isPptx = ext === 'pptx' || ext === 'ppt'
    // 后端 _scan_directory 返回的 path 已经是相对于 workspace 根目录的完整路径
    try {
      setPreviewLoading(true)

      if (isPdf) {
        const blob = await Api.downloadSandboxFile(currentSession, fullPath)
        const pdfBlob = blob.type === 'application/pdf'
          ? blob
          : new Blob([blob], { type: 'application/pdf' })
        setFileContent({ name, content: URL.createObjectURL(pdfBlob), fullPath, isPdf: true })
        return
      }

      if (ext === 'doc') {
        setFileContent({ name, content: '当前浏览器预览主要支持 .docx，.doc 建议下载查看', fullPath, isWord: true })
        return
      }

      if (ext === 'ppt') {
        setFileContent({ name, content: '当前浏览器预览主要支持 .pptx，.ppt 建议下载查看', fullPath, isPptx: true })
        return
      }

      if (ext === 'xlsx' || ext === 'xls') {
        try {
          const bytes = await readBinaryFile(fullPath)
          const workbook = XLSX.read(bytes, { type: 'array' })
          const firstSheet = workbook.Sheets[workbook.SheetNames[0]]
          const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as (string | number)[][]
          if (jsonData.length > 0) {
            const headers = (jsonData[0] || []).map(String)
            const rows = jsonData.slice(1).filter(row => row && row.length > 0)
            setFileContent({ name, content: '', fullPath, isExcel: true, excelData: { headers, rows } })
          } else {
            setFileContent({ name, content: 'Excel 文件为空', fullPath })
          }
        } catch {
          setFileContent({ name, content: 'Excel 预览失败，请下载后查看', fullPath })
        }
        return
      }

      if (isWord) {
        try {
          const bytes = await readBinaryFile(fullPath)
          const result = await mammoth.convertToHtml({ arrayBuffer: bytes.buffer })
          setFileContent({ name, content: result.value || '<p>Word 文件为空</p>', fullPath, isWord: true })
        } catch {
          setFileContent({ name, content: 'Word 预览失败，请下载后查看', fullPath, isWord: true })
        }
        return
      }

      if (isPptx) {
        try {
          const bytes = await readBinaryFile(fullPath)
          const zip = await JSZip.loadAsync(bytes.buffer)
          const slides: string[] = []
          const slideFiles = Object.keys(zip.files)
            .filter(k => /^ppt\/slides\/slide\d+\.xml$/.test(k))
            .sort()
          for (const slideFile of slideFiles) {
            const xml = await zip.file(slideFile)!.async('text')
            const texts: string[] = []
            const regex = /<a:t>([^<]*)<\/a:t>/g
            let m
            while ((m = regex.exec(xml)) !== null) {
              if (m[1].trim()) texts.push(m[1].trim())
            }
            slides.push(texts.join('\n'))
          }
          setFileContent({ name, content: '', fullPath, isPptx: true, pptxSlides: slides })
        } catch {
          setFileContent({ name, content: 'PPT 预览失败，请下载后查看', fullPath, isPptx: true })
        }
        return
      }

      const data = await Api.getSandboxFileContent(currentSession, fullPath)
      if (data.binary) {
        if (data.image) {
          const blob = await Api.downloadSandboxFile(currentSession, fullPath)
          setFileContent({ name, content: URL.createObjectURL(blob), fullPath, isImage: true })
        } else if (isExcel) {
          try {
            const base64 = data.content || ''
            const binary = atob(base64)
            const bytes = new Uint8Array(binary.length)
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
            const workbook = XLSX.read(bytes, { type: 'array' })
            const firstSheet = workbook.Sheets[workbook.SheetNames[0]]
            const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as (string | number)[][]
            if (jsonData.length > 0) {
              const headers = (jsonData[0] || []).map(String)
              const rows = jsonData.slice(1).filter(row => row && row.length > 0)
              setFileContent({ name, content: '', fullPath, isExcel: true, excelData: { headers, rows } })
            } else {
              setFileContent({ name, content: 'Excel 文件为空', fullPath })
            }
          } catch {
            setFileContent({ name, content: 'Excel 预览失败，请下载后查看', fullPath })
          }
        } else if (isWord) {
          try {
            const base64 = data.content || ''
            const binary = atob(base64)
            const bytes = new Uint8Array(binary.length)
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
            const result = await mammoth.convertToHtml({ arrayBuffer: bytes.buffer })
            setFileContent({ name, content: result.value || '<p>Word 文件为空</p>', fullPath, isWord: true })
          } catch {
            setFileContent({ name, content: 'Word 预览失败，请下载后查看', fullPath, isWord: true })
          }
        } else if (isPptx) {
          try {
            const base64 = data.content || ''
            const binary = atob(base64)
            const bytes = new Uint8Array(binary.length)
            for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
            const zip = await JSZip.loadAsync(bytes.buffer)
            const slides: string[] = []
            const slideFiles = Object.keys(zip.files)
              .filter(k => /^ppt\/slides\/slide\d+\.xml$/.test(k))
              .sort()
            for (const slideFile of slideFiles) {
              const xml = await zip.file(slideFile)!.async('text')
              const texts: string[] = []
              const regex = /<a:t>([^<]*)<\/a:t>/g
              let m
              while ((m = regex.exec(xml)) !== null) {
                if (m[1].trim()) texts.push(m[1].trim())
              }
              slides.push(texts.join('\n'))
            }
            setFileContent({ name, content: '', fullPath, isPptx: true, pptxSlides: slides })
          } catch {
            setFileContent({ name, content: 'PPT 预览失败，请下载后查看', fullPath, isPptx: true })
          }
        } else {
          setFileContent({ name, content: `[二进制文件: ${name}]`, fullPath })
        }
      } else if (isHtml) {
        setFileContent({ name, content: data.content ?? '', fullPath, isHtml: true })
      } else if (isExcel) {
        try {
          const workbook = XLSX.read(data.content || '', { type: 'string' })
          const firstSheet = workbook.Sheets[workbook.SheetNames[0]]
          const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 }) as (string | number)[][]
          if (jsonData.length > 0) {
            const headers = (jsonData[0] || []).map(String)
            const rows = jsonData.slice(1).filter(row => row && row.length > 0)
            setFileContent({ name, content: '', fullPath, isExcel: true, excelData: { headers, rows } })
          } else {
            setFileContent({ name, content: 'Excel 文件为空', fullPath })
          }
        } catch {
          setFileContent({ name, content: data.content ?? '', fullPath })
        }
      } else {
        setFileContent({ name, content: data.content ?? '', fullPath })
      }
    } catch {
      setFileContent({ name, content: '无法读取文件内容', fullPath })
    } finally {
      setPreviewLoading(false)
    }
  }

  const formatSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
  }

  const getFileIcon = (name: string) => {
    const ext = name.split('.').pop()?.toLowerCase()
    if (['py', 'js', 'ts', 'tsx', 'jsx', 'html', 'css'].includes(ext || '')) return <FileCode size={14} className="text-accent" />
    if (['xlsx', 'xls', 'csv'].includes(ext || '')) return <FileSpreadsheet size={14} className="text-success" />
    if (['docx', 'doc'].includes(ext || '')) return <FileText size={14} className="text-blue-400" />
    if (ext === 'pdf') return <FileText size={14} className="text-red-400" />
    if (['pptx', 'ppt'].includes(ext || '')) return <FileText size={14} className="text-orange-400" />
    if (['md', 'txt', 'log'].includes(ext || '')) return <FileText size={14} className="text-warning" />
    return <File size={14} className="text-text-muted" />
  }

  const breadcrumbs = currentPath ? currentPath.split('/').filter(Boolean) : []

  if (fileContent) {
    return (
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
          <button onClick={() => setFileContent(null)} className="text-text-muted hover:text-text-primary cursor-pointer">
            <ArrowLeft size={14} />
          </button>
          <span className="text-xs font-medium text-text-primary truncate">{fileContent.name}</span>
          <div className="flex-1" />
          {fileContent.isHtml && (
            <button
              type="button"
              onClick={() => openHtmlInNewPage(fileContent.content)}
              className="text-text-muted hover:text-accent transition-colors"
              title="新页面显示"
            >
              <ExternalLink size={14} />
            </button>
          )}
          <button
            type="button"
            onClick={() => void downloadFile(fileContent.fullPath, fileContent.name)}
            className="text-text-muted hover:text-accent transition-colors"
            title="下载文件"
          >
            <Download size={14} />
          </button>
        </div>
        {fileContent.isImage ? (
          <div className="flex-1 overflow-auto p-3 flex items-center justify-center bg-bg-base">
            <img
              src={fileContent.content}
              alt={fileContent.name}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        ) : fileContent.isExcel && fileContent.excelData ? (
          <div className="flex-1 overflow-auto p-2" style={{ background: '#1e1e2e' }}>
            <table className="w-full text-xs border-collapse" style={{ color: '#cdd6f4' }}>
              <thead>
                <tr style={{ background: '#313244' }}>
                  {fileContent.excelData.headers.map((h, i) => (
                    <th key={i} className="px-3 py-2 text-left font-medium border-b" style={{ borderColor: '#45475a', color: '#a6adc8' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fileContent.excelData.rows.map((row, ri) => (
                  <tr key={ri} className="hover:opacity-90">
                    {row.map((cell, ci) => (
                      <td key={ci} className="px-3 py-1.5 border-b" style={{ borderColor: '#313244', color: '#cdd6f4' }}>
                        {cell ?? ''}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : fileContent.isWord && fileContent.content.trim().startsWith('<') ? (
          <iframe
            srcDoc={fileContent.content}
            className="flex-1 w-full border-0 bg-white"
            title={`${fileContent.name} preview`}
            sandbox=""
          />
        ) : fileContent.isWord ? (
          <div className="flex-1 flex items-center justify-center p-4 text-sm" style={{ background: '#1e1e2e', color: '#a6adc8' }}>
            {fileContent.content}
          </div>
        ) : fileContent.isPdf ? (
          <PdfViewer url={fileContent.content} title={fileContent.name} />
        ) : fileContent.isPptx && fileContent.pptxSlides ? (
          <PptxViewer slides={fileContent.pptxSlides} />
        ) : fileContent.isPptx ? (
          <div className="flex-1 flex items-center justify-center p-4 text-sm" style={{ background: '#1e1e2e', color: '#a6adc8' }}>
            {fileContent.content}
          </div>
        ) : fileContent.isHtml ? (
          <iframe
            srcDoc={fileContent.content}
            className="flex-1 w-full border-0 bg-white"
            title={fileContent.name}
            sandbox=""
          />
        ) : (
          <pre className="flex-1 overflow-auto p-3 text-xs text-text-secondary bg-bg-base leading-relaxed whitespace-pre-wrap break-all">
            {fileContent.content}
          </pre>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <div className="flex items-center gap-1 text-xs text-text-muted flex-1 min-w-0">
          <button
            onClick={() => loadFiles('')}
            className="hover:text-accent transition-colors cursor-pointer shrink-0"
          >
            workspace
          </button>
          {breadcrumbs.map((crumb, i) => (
            <span key={i} className="flex items-center gap-1">
              <ChevronRight size={10} />
              <button
                onClick={() => loadFiles(breadcrumbs.slice(0, i + 1).join('/'))}
                className="hover:text-accent transition-colors cursor-pointer truncate"
              >
                {crumb}
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-1">
          {(previewLoading || loading) && <span className="text-[10px] text-text-muted mr-1">加载中...</span>}
          <button
            type="button"
            onClick={() => void downloadZip()}
            className="p-1 text-text-muted hover:text-accent transition-colors"
            title="下载全部(ZIP)"
          >
            <Download size={14} />
          </button>
          <button onClick={() => loadFiles(currentPath)} className="p-1 text-text-muted hover:text-accent transition-colors cursor-pointer" title="刷新">
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-1.5">
        {files.length === 0 ? (
          <div className="text-xs text-text-muted text-center py-8">空目录</div>
        ) : (
          files.map((f) => (
            <div
              key={f.path}
              onClick={() => f.is_dir ? loadFiles(f.path) : viewFile(f.path, f.name)}
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-bg-hover cursor-pointer group transition-colors"
            >
              {f.is_dir ? (
                <Folder size={14} className="text-warning shrink-0" />
              ) : (
                getFileIcon(f.name)
              )}
              <span className="text-xs text-text-primary truncate flex-1">{f.name}</span>
              {!f.is_dir && f.size !== undefined && (
                <span className="text-[10px] text-text-muted shrink-0">{formatSize(f.size)}</span>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
