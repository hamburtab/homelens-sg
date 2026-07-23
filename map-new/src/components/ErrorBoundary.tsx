import { Component } from 'react';
import type { ReactNode } from 'react';

interface P { children: ReactNode; }
interface S { error: Error | null; }

export class ErrorBoundary extends Component<P, S> {
  state: S = { error: null };
  static getDerivedStateFromError(e: Error) { return { error: e }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding:40, textAlign:'center', fontFamily:'sans-serif' }}>
          <h2>地图加载失败</h2>
          <p style={{ color:'#dc2626' }}>{this.state.error.message}</p>
          <button onClick={() => this.setState({ error:null })} style={{ marginTop:12, padding:'8px 16px', cursor:'pointer' }}>重试</button>
        </div>
      );
    }
    return this.props.children;
  }
}
