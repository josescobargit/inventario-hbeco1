import { CSSProperties, useEffect, useRef, useState } from "react";
import type {
  PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy,
} from "pdfjs-dist";

let pdfModulePromise: Promise<typeof import("pdfjs-dist")> | null = null;
async function loadPdfJs() {
  pdfModulePromise ??= import("pdfjs-dist").then((module) => {
    module.GlobalWorkerOptions.workerSrc = new URL(
      "pdfjs-dist/build/pdf.worker.min.mjs",
      import.meta.url,
    ).toString();
    return module;
  });
  return pdfModulePromise;
}

type FitMode = "custom" | "width" | "page";

export interface ViewableDocument {
  token: string;
  filename: string;
  content_type: string;
  page_count?: number;
}

function PdfCanvas({
  page, zoom, rotation, fitMode, availableWidth, availableHeight, pageRef, highlight,
}: {
  page: PDFPageProxy;
  zoom: number;
  rotation: number;
  fitMode: FitMode;
  availableWidth: number;
  availableHeight: number;
  pageRef: (element: HTMLDivElement | null) => void;
  highlight?: { x: number; y: number; width: number; height: number } | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [error, setError] = useState<string | null>(null);
  const base = page.getViewport({ scale: 1, rotation });
  const widthScale = Math.max(.2, (availableWidth - 32) / base.width);
  const pageScale = Math.max(.2, Math.min(widthScale, (availableHeight - 32) / base.height));
  const scale = fitMode === "width" ? widthScale : fitMode === "page" ? pageScale : zoom / 100;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !availableWidth) return;
    const viewport = page.getViewport({ scale, rotation });
    const outputScale = Math.min(window.devicePixelRatio || 1, 2);
    const context = canvas.getContext("2d");
    if (!context) return;
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${Math.floor(viewport.width)}px`;
    canvas.style.height = `${Math.floor(viewport.height)}px`;
    const task = page.render({
      canvas,
      canvasContext: context,
      viewport,
      transform: outputScale === 1 ? undefined : [outputScale, 0, 0, outputScale, 0, 0],
    });
    task.promise.then(() => setError(null)).catch((caught: unknown) => {
      if ((caught as { name?: string }).name !== "RenderingCancelledException") {
        setError("No se pudo dibujar esta página.");
      }
    });
    return () => task.cancel();
  }, [availableHeight, availableWidth, page, rotation, scale]);
  return <div className="pdf-page" ref={pageRef}>
    <canvas ref={canvasRef} aria-label={`Página ${page.pageNumber}`} />
    {highlight && rotation === 0 && <span
      className="pdf-source-highlight"
      style={{
        left: highlight.x * scale, top: highlight.y * scale,
        width: highlight.width * scale, height: highlight.height * scale,
      }}
    />}
    {error && <span className="viewer-page-error">{error}</span>}
  </div>;
}

function PdfViewer({
  url, highlight,
}: {
  url: string;
  highlight?: { page: number; x: number; y: number; width: number; height: number } | null;
}) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [pages, setPages] = useState<PDFPageProxy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [zoom, setZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const [fitMode, setFitMode] = useState<FitMode>("width");
  const [size, setSize] = useState({ width: 0, height: 650 });
  const stageRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Array<HTMLDivElement | null>>([]);

  useEffect(() => {
    let task: PDFDocumentLoadingTask | null = null;
    let cancelled = false;
    void loadPdfJs().then(async (module) => {
      if (cancelled) return;
      task = module.getDocument({ url, withCredentials: true });
      const loaded = await task.promise;
      const loadedPages = await Promise.all(
        Array.from({ length: loaded.numPages }, (_, index) => loaded.getPage(index + 1)),
      );
      if (!cancelled) {
        setPdf(loaded); setPages(loadedPages); setLoading(false);
      }
    }).catch((caught: unknown) => {
      if (!cancelled) {
        console.error("purchase_order_pdf_load_failed", caught);
        setError("No pudimos renderizar el PDF. Verifica tu sesión o vuelve a intentarlo.");
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  const goToPage = (page: number) => {
    const next = Math.min(Math.max(page, 1), pdf?.numPages ?? 1);
    setCurrentPage(next);
    pageRefs.current[next - 1]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  useEffect(() => {
    if (!highlight?.page) return;
    const frame = window.requestAnimationFrame(() => {
      setCurrentPage(highlight.page);
      pageRefs.current[highlight.page - 1]?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [highlight?.page, pages.length]);

  return <div className="pdf-viewer">
    <div className="viewer-toolbar">
      <button type="button" disabled={currentPage <= 1} onClick={() => goToPage(currentPage - 1)} aria-label="Página anterior">‹</button>
      <span>Página <input aria-label="Página actual" type="number" min={1} max={pdf?.numPages ?? 1} value={currentPage} onChange={(event) => goToPage(Number(event.target.value))} /> de {pdf?.numPages ?? "—"}</span>
      <button type="button" disabled={currentPage >= (pdf?.numPages ?? 1)} onClick={() => goToPage(currentPage + 1)} aria-label="Página siguiente">›</button>
      <span className="toolbar-separator" />
      <button type="button" onClick={() => { setFitMode("custom"); setZoom((value) => Math.max(25, value - 10)); }} aria-label="Reducir zoom">−</button>
      <span>{fitMode === "custom" ? `${zoom}%` : fitMode === "width" ? "Ancho" : "Página"}</span>
      <button type="button" onClick={() => { setFitMode("custom"); setZoom((value) => Math.min(300, value + 10)); }} aria-label="Aumentar zoom">+</button>
      <button type="button" onClick={() => setFitMode("width")}>Ajustar ancho</button>
      <button type="button" onClick={() => setFitMode("page")}>Ajustar página</button>
      <button type="button" onClick={() => setRotation((value) => (value + 90) % 360)}>Rotar</button>
    </div>
    <div className="pdf-stage viewer-stage" ref={stageRef} onScroll={() => {
      const stageTop = stageRef.current?.getBoundingClientRect().top ?? 0;
      let nearest = 0; let distance = Number.POSITIVE_INFINITY;
      pageRefs.current.forEach((element, index) => {
        if (!element) return;
        const nextDistance = Math.abs(element.getBoundingClientRect().top - stageTop);
        if (nextDistance < distance) { distance = nextDistance; nearest = index; }
      });
      setCurrentPage(nearest + 1);
    }}>
      {loading && <div className="viewer-state">Cargando PDF…</div>}
      {error && <div className="viewer-state error">{error}</div>}
      {!loading && !error && pages.map((page, index) => <PdfCanvas
        key={page.pageNumber}
        page={page}
        zoom={zoom}
        rotation={rotation}
        fitMode={fitMode}
        availableWidth={size.width}
        availableHeight={size.height}
        pageRef={(element) => { pageRefs.current[index] = element; }}
        highlight={highlight?.page === page.pageNumber ? highlight : null}
      />)}
    </div>
  </div>;
}

export function DocumentViewer({
  document, url, className = "", highlight = null,
}: {
  document: ViewableDocument;
  url: string;
  className?: string;
  highlight?: { page: number; x: number; y: number; width: number; height: number } | null;
}) {
  const [reloadKey, setReloadKey] = useState(0);
  const [imageError, setImageError] = useState(false);
  const [imageZoom, setImageZoom] = useState(100);
  const [rotation, setRotation] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const download = async () => {
    try {
      const response = await fetch(url, { credentials: "include" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blobUrl = URL.createObjectURL(await response.blob());
      const link = window.document.createElement("a");
      link.href = blobUrl; link.download = document.filename; link.click();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1_000);
    } catch (caught) {
      console.error("purchase_order_document_download_failed", caught);
    }
  };
  const fullscreen = () => containerRef.current?.requestFullscreen().catch((caught) => {
    console.error("purchase_order_document_fullscreen_failed", caught);
  });
  return <section className={`integrated-document-viewer ${className}`} ref={containerRef}>
    <header className="document-viewer-header">
      <div><strong>{document.filename}</strong><span>{document.page_count ? `${document.page_count} página${document.page_count === 1 ? "" : "s"}` : document.content_type}</span></div>
      <div>
        <button type="button" onClick={fullscreen}>Pantalla completa</button>
        <a href={url} target="_blank" rel="noreferrer">Abrir original</a>
        <button type="button" onClick={download}>Descargar</button>
      </div>
    </header>
    {document.content_type === "application/pdf" && <PdfViewer key={`${url}-${reloadKey}`} url={url} highlight={highlight} />}
    {document.content_type.startsWith("image/") && <>
      <div className="viewer-toolbar">
        <button type="button" onClick={() => setImageZoom((value) => Math.max(25, value - 10))}>−</button>
        <span>{imageZoom}%</span>
        <button type="button" onClick={() => setImageZoom((value) => Math.min(300, value + 10))}>+</button>
        <button type="button" onClick={() => setImageZoom(100)}>Ajustar</button>
        <button type="button" onClick={() => setRotation((value) => (value + 90) % 360)}>Rotar</button>
      </div>
      <div className="image-stage viewer-stage">
        {!imageError ? <img
          src={`${url}${url.includes("?") ? "&" : "?"}retry=${reloadKey}`}
          alt={`Documento ${document.filename}`}
          style={{ "--image-zoom": imageZoom / 100, "--image-rotation": `${rotation}deg` } as CSSProperties}
          onError={(event) => { console.error("purchase_order_image_load_failed", event); setImageError(true); }}
        /> : <div className="viewer-state error">No pudimos mostrar la imagen. Revisa tu sesión o vuelve a intentarlo.</div>}
      </div>
    </>}
    {document.content_type === "text/plain" && <div className="viewer-state">El original es texto pegado y se muestra en los datos reconocidos.</div>}
    {(imageError) && <button className="viewer-retry" type="button" onClick={() => { setImageError(false); setReloadKey((value) => value + 1); }}>Reintentar</button>}
    {document.content_type === "application/pdf" && <button className="viewer-retry" type="button" onClick={() => setReloadKey((value) => value + 1)}>Recargar PDF</button>}
  </section>;
}
