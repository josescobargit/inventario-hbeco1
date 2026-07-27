import { Component, ErrorInfo, ReactNode } from "react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Error de interfaz no controlado", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <main className="loading-screen" role="alert">
          <strong>No pudimos mostrar esta pantalla</strong>
          <span>{this.state.error.message || "Ocurrió un error inesperado de interfaz."}</span>
          <button type="button" onClick={() => this.setState({ error: null })}>
            Volver a intentar
          </button>
        </main>
      );
    }
    return this.props.children;
  }
}
