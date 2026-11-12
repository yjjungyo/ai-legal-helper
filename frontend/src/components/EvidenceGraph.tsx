/**
 * @fileoverview 증거 지식 그래프(Evidence Knowledge Graph) 시각화 컴포넌트
 *
 * Neo4j 파생 그래프(Case, Fact, Event, LegalIssue, Claim, Document)의 노드 및 엣지를 시각화합니다.
 * 화면 크기에 맞춰 대형 캔버스를 동적으로 채우고(ResizeObserver), 노드 간 반발력(charge) 및
 * 링크 거리(link distance)를 최적화하여 노드 밀집 및 텍스트 겹침을 방지합니다.
 */

import React, { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { getCaseGraph, getGraphAnalysis } from '../api/graphClient';

interface Props {
  caseId: string;
}

export const EvidenceGraph: React.FC<Props> = ({ caseId }) => {
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] });
  const [analysis, setAnalysis] = useState<any>(null);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 900, height: 700 });

  // 컨테이너 크기 측정 및 반응형 리사이징
  useEffect(() => {
    if (!containerRef.current) return;
    
    const updateSize = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        if (clientWidth > 0 && clientHeight > 0) {
          setDimensions({
            width: clientWidth,
            height: clientHeight,
          });
        }
      }
    };

    updateSize();

    const observer = new ResizeObserver(() => {
      updateSize();
    });
    observer.observe(containerRef.current);

    return () => observer.disconnect();
  }, []);

  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError('');
    setSelectedNode(null);
    try {
      const graphRes = await getCaseGraph(caseId);
      if (graphRes.available === false) {
        setError('그래프 데이터베이스(Neo4j)를 사용할 수 없습니다.');
      } else {
        const nodes = graphRes.nodes || [];
        const links = (graphRes.edges || []).map((e: any) => ({
          ...e,
          name: e.type,
        }));
        setGraphData({ nodes, links });
      }

      const anaRes = await getGraphAnalysis(caseId);
      if (anaRes && anaRes.available) {
        setAnalysis(anaRes);
      }
    } catch (e: any) {
      setError(e.message || '그래프를 불러오는 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // 노드 반발력 및 링크 거리 최적화 (뭉침 현상 방지)
  useEffect(() => {
    if (fgRef.current && graphData.nodes.length > 0) {
      try {
        const charge = fgRef.current.d3Force('charge');
        if (charge) {
          const strength = graphData.nodes.length > 60 ? -350 : -240;
          charge.strength(strength);
        }
        const link = fgRef.current.d3Force('link');
        if (link) {
          link.distance(65);
        }
        fgRef.current.d3ReheatSimulation();
      } catch {
        // safe fallback
      }
    }
  }, [graphData]);

  const handleZoomIn = () => {
    if (fgRef.current) {
      fgRef.current.zoom(fgRef.current.zoom() * 1.35, 300);
    }
  };

  const handleZoomOut = () => {
    if (fgRef.current) {
      fgRef.current.zoom(fgRef.current.zoom() / 1.35, 300);
    }
  };

  const handleZoomToFit = () => {
    if (fgRef.current) {
      fgRef.current.zoomToFit(500, 60);
    }
  };

  const getNodeColor = (type: string) => {
    switch (type) {
      case 'Case': return '#868e96';
      case 'Fact': return '#1976d2';
      case 'Event': return '#f59f00';
      case 'LegalIssue': return '#e03131';
      case 'EvidenceClaim': return '#2f9e44';
      case 'EvidenceDocument': return '#7950f2';
      case 'Party': return '#1098ad';
      default: return '#adb5bd';
    }
  };

  const getLinkColor = (type: string) => {
    if (type === 'SUPPORTS') return 'rgba(47, 158, 68, 0.7)';
    if (type === 'CONTRADICTS') return 'rgba(224, 49, 49, 0.85)';
    return 'rgba(173, 181, 189, 0.5)';
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: '650px',
      backgroundColor: '#fff',
      border: '1px solid var(--border, #e2e8f0)',
      borderRadius: '8px',
      padding: '16px 20px',
      boxSizing: 'border-box',
    }}>
      {/* 상단 툴바 및 컨트롤 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <h3 style={{ margin: 0, fontSize: '1.15em', fontWeight: 750, color: 'var(--text-main, #0f172a)' }}>
            🕸️ 증거 지식 그래프 (Evidence Knowledge Graph)
          </h3>
          {graphData.nodes.length > 0 && (
            <span style={{
              fontSize: '0.82em',
              padding: '3px 9px',
              backgroundColor: '#eff6ff',
              color: '#1d4ed8',
              borderRadius: '999px',
              border: '1px solid #bfdbfe',
              fontWeight: 600
            }}>
              노드 {graphData.nodes.length}개 · 관계 {graphData.links.length}개
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <button 
            type="button"
            onClick={handleZoomIn} 
            title="그래프 확대"
            style={{ padding: '6px 11px', cursor: 'pointer', borderRadius: '5px', border: '1px solid #cbd5e1', backgroundColor: '#fff', fontSize: '0.88em', fontWeight: 500 }}
          >
            🔍＋ 확대
          </button>
          <button 
            type="button"
            onClick={handleZoomOut} 
            title="그래프 축소"
            style={{ padding: '6px 11px', cursor: 'pointer', borderRadius: '5px', border: '1px solid #cbd5e1', backgroundColor: '#fff', fontSize: '0.88em', fontWeight: 500 }}
          >
            🔍－ 축소
          </button>
          <button 
            type="button"
            onClick={handleZoomToFit} 
            title="화면 크기에 맞춤"
            style={{ padding: '6px 13px', cursor: 'pointer', borderRadius: '5px', border: '1px solid #cbd5e1', backgroundColor: '#fff', fontSize: '0.88em', fontWeight: 500 }}
          >
            🎯 화면 맞춤
          </button>
          <button 
            type="button"
            onClick={loadGraph} 
            title="그래프 데이터 새로고침"
            style={{ padding: '6px 13px', cursor: 'pointer', borderRadius: '5px', border: '1px solid #cbd5e1', backgroundColor: '#fff', fontSize: '0.88em', fontWeight: 500 }}
          >
            🔄 새로고침
          </button>
        </div>
      </div>

      {loading && <p style={{ color: '#64748b', padding: '20px' }}>그래프 데이터를 불러오는 중입니다...</p>}
      {error && <p style={{ color: '#e03131', padding: '20px' }}>⚠️ {error}</p>}
      
      {!loading && !error && (
        <div style={{ display: 'flex', gap: '16px', flex: 1, minHeight: 0, height: '100%' }}>
          {/* 그래프 캔버스 컨테이너 (남는 여백 없이 최대 크기 활용) */}
          <div 
            ref={containerRef}
            style={{ 
              flex: 1, 
              minWidth: 0, 
              height: '100%', 
              border: '1px solid #e2e8f0', 
              borderRadius: '8px',
              position: 'relative', 
              overflow: 'hidden',
              backgroundColor: '#fafbfc'
            }}
          >
            <ForceGraph2D
              ref={fgRef}
              width={dimensions.width}
              height={dimensions.height}
              graphData={graphData}
              nodeLabel={(node: any) => `${node.type}: ${node.label || node.id}`}
              nodeColor={(node: any) => getNodeColor(node.type)}
              nodeRelSize={7}
              linkColor={(link: any) => getLinkColor(link.type)}
              linkWidth={(link: any) => link.type === 'CONTRADICTS' ? 2.5 : 1.2}
              linkDirectionalArrowLength={4.5}
              linkDirectionalArrowRelPos={1}
              d3VelocityDecay={0.3}
              cooldownTicks={140}
              warmupTicks={40}
              onEngineStop={handleZoomToFit}
              onNodeClick={(node: any) => {
                setSelectedNode(node);
                if (fgRef.current) {
                  fgRef.current.centerAt(node.x, node.y, 400);
                  fgRef.current.zoom(1.8, 400);
                }
              }}
              nodeCanvasObject={(node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
                const label = node.label || node.id || '';
                const fontSize = Math.max(9, Math.min(13, 11 / Math.max(globalScale, 0.6)));
                ctx.font = `500 ${fontSize}px sans-serif`;

                // Node circle
                ctx.beginPath();
                ctx.arc(node.x, node.y, 7, 0, 2 * Math.PI, false);
                ctx.fillStyle = getNodeColor(node.type);
                ctx.fill();
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1.8;
                ctx.stroke();

                // Node text label with halo for high contrast and readability
                if (globalScale > 0.45) {
                  ctx.textAlign = 'center';
                  ctx.textBaseline = 'top';
                  const truncated = label.length > 20 ? label.slice(0, 18) + '...' : label;
                  ctx.strokeStyle = 'rgba(255, 255, 255, 0.9)';
                  ctx.lineWidth = 3;
                  ctx.strokeText(truncated, node.x, node.y + 9);
                  ctx.fillStyle = '#1e293b';
                  ctx.fillText(truncated, node.x, node.y + 9);
                }
              }}
            />
          </div>

          {/* 우측 분석 및 선택 노드 정보 패널 (슬림 고정 사이드바) */}
          <div style={{ 
            width: '360px', 
            minWidth: '320px', 
            maxWidth: '400px', 
            height: '100%', 
            overflowY: 'auto', 
            padding: '16px', 
            backgroundColor: '#f8fafc', 
            border: '1px solid #e2e8f0', 
            borderRadius: '8px',
            boxSizing: 'border-box'
          }}>
            {selectedNode ? (
              <div style={{ marginBottom: '20px', padding: '12px', backgroundColor: '#fff', borderRadius: '6px', border: '1px solid #d0ebff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <strong style={{ color: '#1976d2' }}>📌 선택된 노드 상세</strong>
                  <button onClick={() => setSelectedNode(null)} style={{ padding: '2px 6px', fontSize: '11px', cursor: 'pointer' }}>닫기</button>
                </div>
                <div style={{ fontSize: '13px', lineHeight: '1.6' }}>
                  <div><strong>유형:</strong> <span style={{ color: getNodeColor(selectedNode.type), fontWeight: 'bold' }}>{selectedNode.type}</span></div>
                  <div><strong>내용:</strong> {selectedNode.label || selectedNode.id}</div>
                  {selectedNode.props && (
                    <div style={{ marginTop: '6px', fontSize: '12px', color: '#666' }}>
                      {selectedNode.props.date && <div>📅 일시: {selectedNode.props.date}</div>}
                      {selectedNode.props.status && <div>상태: {selectedNode.props.status}</div>}
                      {selectedNode.props.confidence && <div>신뢰도: {(selectedNode.props.confidence * 100).toFixed(0)}%</div>}
                    </div>
                  )}
                </div>
              </div>
            ) : null}

            <h4 style={{ margin: '0 0 12px 0', borderBottom: '1px solid #eee', paddingBottom: '6px', color: '#0f172a' }}>📊 지식 그래프 분석</h4>
            
            {analysis && (
              <div style={{ fontSize: '13px' }}>
                <div style={{ marginBottom: '15px' }}>
                  <strong style={{ color: '#e03131' }}>⚠️ 증거 공백 (Evidence Gaps)</strong>
                  <p style={{ margin: '4px 0', fontSize: '12px', color: '#666' }}>입증 증거가 연결되지 않은 사실이나 쟁점:</p>
                  <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
                    {analysis.evidence_gaps?.map((g: any, i: number) => (
                      <li key={i} style={{ marginBottom: '4px' }}>
                        <span style={{ fontWeight: 'bold' }}>[{g.node_type}]</span> {g.content}
                      </li>
                    ))}
                    {(!analysis.evidence_gaps || analysis.evidence_gaps.length === 0) && (
                      <li style={{ color: '#2b8a3e' }}>발견된 증거 공백이 없습니다.</li>
                    )}
                  </ul>
                </div>

                <div>
                  <strong style={{ color: '#d9480f' }}>⚡ 상충 증거 (Contradictions)</strong>
                  <p style={{ margin: '4px 0', fontSize: '12px', color: '#666' }}>서로 모순되거나 충돌하는 진술/증거:</p>
                  <div style={{ marginTop: '6px' }}>
                    {analysis.contradictions && analysis.contradictions.length > 0 ? (
                      analysis.contradictions.map((c: any, i: number) => (
                        <div
                          key={i}
                          style={{
                            marginBottom: '8px',
                            padding: '8px 10px',
                            background: '#fff9db',
                            border: '1px solid #ffe066',
                            borderRadius: '4px',
                            fontSize: '12px',
                          }}
                        >
                          <div style={{ color: '#d9480f', fontWeight: 'bold', marginBottom: '3px' }}>
                            상충 #{i + 1} [{c.target_type || 'Fact'}]
                          </div>
                          <div style={{ color: '#333', marginBottom: '2px' }}>
                            <span style={{ fontWeight: 'bold', color: '#495057' }}>확정 사실:</span> {c.target_content}
                          </div>
                          {c.contradicting_statement && (
                            <div style={{ color: '#c92a2a' }}>
                              <span style={{ fontWeight: 'bold' }}>상충 진술:</span> {c.contradicting_statement}
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <p style={{ color: '#2b8a3e', fontSize: '12px', margin: '4px 0' }}>상충되는 증거가 없습니다.</p>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 하단 범례 */}
      <div style={{ 
        marginTop: '12px', 
        paddingTop: '10px', 
        borderTop: '1px solid #e2e8f0', 
        fontSize: '12.5px', 
        display: 'flex', 
        alignItems: 'center', 
        gap: '14px', 
        flexWrap: 'wrap',
        color: '#475569'
      }}>
        <strong style={{ color: '#0f172a' }}>범례: </strong>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#1976d2', fontSize: '1.2em' }}>●</span> Fact (사실)</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#f59f00', fontSize: '1.2em' }}>●</span> Event (타임라인)</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#e03131', fontSize: '1.2em' }}>●</span> LegalIssue (법률 쟁점)</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#2f9e44', fontSize: '1.2em' }}>●</span> Claim (추출 주장)</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#7950f2', fontSize: '1.2em' }}>●</span> Document (증거 문서)</span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><span style={{ color: '#868e96', fontSize: '1.2em' }}>●</span> EvidenceSpan (증거원문)</span>
      </div>
    </div>
  );
};
