import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const pdfMocks = vi.hoisted(() => {
  const viewport = vi.fn(({ scale, rotation = 0 }: { scale: number; rotation?: number }) => ({
    width: (rotation % 180 ? 800 : 600) * scale,
    height: (rotation % 180 ? 600 : 800) * scale,
  }));
  const page = (pageNumber: number) => ({
    pageNumber,
    getViewport: viewport,
    render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() })),
  });
  const document = {
    numPages: 2,
    getPage: vi.fn((number: number) => Promise.resolve(page(number))),
  };
  return {
    viewport,
    getDocument: vi.fn(() => ({
      promise: Promise.resolve(document),
      destroy: vi.fn(),
    })),
  };
});

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: pdfMocks.getDocument,
}));

import { DocumentViewer } from "./DocumentViewer";

beforeAll(() => {
  class ResizeObserverMock {
    callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) { this.callback = callback; }
    observe() { this.callback([{ contentRect: { width: 800, height: 650 } } as ResizeObserverEntry], this as unknown as ResizeObserver); }
    disconnect() {}
  }
  vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    value: vi.fn(() => ({})),
  });
  Element.prototype.scrollIntoView = vi.fn();
  HTMLElement.prototype.requestFullscreen = vi.fn(() => Promise.resolve());
});
afterEach(() => cleanup());

describe("DocumentViewer", () => {
  it("renderiza todas las páginas PDF y permite navegar, ampliar, rotar y usar pantalla completa", async () => {
    const rendered = render(<DocumentViewer
      document={{ token: "one", filename: "orden.pdf", content_type: "application/pdf", page_count: 2 }}
      url="/api/v1/purchase-orders/imports/one/content"
      highlight={{ page: 2, x: 20, y: 30, width: 200, height: 15 }}
    />);
    expect(screen.getByText("Cargando PDF…")).toBeVisible();
    expect(await screen.findByLabelText("Página 1")).toBeInTheDocument();
    expect(screen.getByLabelText("Página 2")).toBeInTheDocument();
    await waitFor(() => expect(rendered.container.querySelector(".pdf-source-highlight")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Página siguiente"));
    expect(screen.getByLabelText("Página actual")).toHaveValue(2);
    fireEvent.click(screen.getByLabelText("Aumentar zoom"));
    expect(within(rendered.container).getByText("110%")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Rotar" }));
    await waitFor(() => expect(pdfMocks.viewport).toHaveBeenCalledWith(expect.objectContaining({ rotation: 90 })));
    fireEvent.click(screen.getByRole("button", { name: "Pantalla completa" }));
    expect(HTMLElement.prototype.requestFullscreen).toHaveBeenCalled();
  });

  it("usa el visor de imágenes con zoom y rotación en vez de PDF.js", () => {
    render(<DocumentViewer
      document={{ token: "image", filename: "orden.png", content_type: "image/png" }}
      url="/api/v1/purchase-orders/imports/image/content"
    />);
    expect(screen.getByAltText("Documento orden.png")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "+" }));
    expect(screen.getByText("110%")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Rotar" }));
    expect(screen.getByAltText("Documento orden.png")).toHaveStyle("--image-rotation: 90deg");
  });
});
