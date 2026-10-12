import React, { useEffect, useState, useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { getCaseGraph, getGraphAnalysis } from '../api/graphClient';

interface Props {
  caseId: string;
}

/**
 * 증거 지식 그래프(Evidence Knowledge Graph) 시각화 컴포넌트.
 *
 * 주요 기능:
 * 1. Neo4j 파생 그래프(Case, Fact, Event, LegalIssue, Claim, Document) 노드 및 엣지 시각화.
 * 2. 캔버스 컨테이너 크기 자동 측정(ResizeObserver)으로 우하단 쏠림 현상 및 오버플로우 방지.
 * 3. 시뮬레이션 완료 시 화면 자동 맞춤(zoomToFit) 및 노드 텍스트 라벨 렌더링.
 * 4. 증거 공백(Evidence Gaps) 및 상충 증거(Contradictions) 분석 패널 제공.
 * 5. 노드 클릭 시 상세 속성 팝업/조회 지원.
 */
export const EvidenceGraph: React.FC<Props> = ({ caseId }) => {
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] });
  const [analysis, setAnalysis] = useState<any>(null);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  
  const containerRef = useRef<HTMLDivElement>(null);
  const fgRef = useRef<any>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number }>({ width: 600, height: 520 });

  // 컨테이너 크기 측정 및 반응형 리사이징
  useEffect(() => {
    if (!containerRef.current) return;
    
    const updateSize = () => {
      if (containerRef.current) {
        const { clientWidth, clientHeight } = containerRef.current;
        if (clientWidth > 0) {
          setDimensions({
            width: clientWidth,
            height: clientHeight > 0 ? clientHeight : 520,
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
        // react-force-graph expects 'links' instead of 'edges'
        const nodes = graphRes.nodes || [];
        const links = (graphRes.edges || []).map((e: any) => ({
          ...e,
          name: e.type // edge label
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

  const handleZoomToFit = () => {
    if (fgRef.current) {
      fgRef.current.zoomToFit(400, 40);
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
    <div style={{ marginTop: '20px', border: '1px solid #ddd', borderRadius: '8px', padding: '16px', backgroundColor: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '15px' }}>
        <h3 style={{ margin: 0 }}>🕸️ 증거 지식 그래프 (Evidence Knowledge Graph)</h3>
        <div>
          <button 
            onClick={handleZoomToFit} 
            style={{ padding: '6px 12px', marginRight: '8px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc' }}
          >
            🎯 화면 맞춤
          </button>
          <button 
            onClick={loadGraph} 
            style={{ padding: '6px 12px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc' }}
          >
            🔄 새로고침
          </button>
        </div>
      </div>

      {loading && <p style={{ color: '#666' }}>그래프 데이터를 불러오는 중입니다...</p>}
      {error && <p style={{ color: '#e03131' }}>⚠️ {error}</p>}
      
      {!loading && !error && (
        <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
          {/* 그래프 캔버스 컨테이너 (정확한 width/height 전달 및 오버플로우 방지) */}
          <div 
            ref={containerRef}
            style={{ 
              flex: '2 1 500px', 
              minWidth: '320px', 
              height: '520px', 
              border: '1px solid #e0e0e0', 
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
              nodeRelSize={6}
              linkColor={(link: any) => getLinkColor(link.type)}
              linkWidth={(link: any) => link.type === 'CONTRADICTS' ? 2.5 : 1.2}
              linkDirectionalArrowLength={4}
              linkDirectionalArrowRelPos={1}
              cooldownTicks={120}
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
                const fontSize = 11 / Math.max(globalScale, 0.8);
                ctx.font = `${fontSize}px sans-serif`;

                // Node circle
                ctx.beginPath();
                ctx.arc(node.x, node.y, 6, 0, 2 * Math.PI, false);
                ctx.fillStyle = getNodeColor(node.type);
                ctx.fill();
                ctx.strokeStyle = '#ffffff';
                ctx.lineWidth = 1.5;
                ctx.stroke();

                // Node text label
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                ctx.fillStyle = '#333333';
                const truncated = label.length > 16 ? label.slice(0, 16) + '...' : label;
                ctx.fillText(truncated, node.x, node.y + 8);
              }}
            />
          </div>

          {/* 우측 분석 및 선택 노드 정보 패널 */}
          <div style={{ 
            flex: '1 1 280px', 
            minWidth: '260px', 
            overflowY: 'auto', 
            maxHeight: '520px', 
            padding: '15px', 
            backgroundColor: '#f8f9fa', 
            border: '1px solid #e0e0e0', 
            borderRadius: '8px' 
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

            <h4 style={{ margin: '0 0 12px 0', borderBottom: '1px solid #eee', paddingBottom: '6px' }}>📊 지식 그래프 분석</h4>
            
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
                  <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
                    {analysis.contradictions?.map((c: any, i: number) => (
                      <li key={i} style={{ marginBottom: '4px' }}>
                        <span style={{ fontWeight: 'bold' }}>[{c.target_type}]</span> {c.target_content}
                      </li>
                    ))}
                    {(!analysis.contradictions || analysis.contradictions.length === 0) && (
                      <li style={{ color: '#2b8a3e' }}>상충되는 증거가 없습니다.</li>
                    )}
                  </ul>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* 하단 범례 */}
      <div style={{ marginTop: '15px', paddingTop: '10px', borderTop: '1px solid #eee', fontSize: '13px', display: 'flex', gap: '15px', flexWrap: 'wrap' }}>
        <strong>범례: </strong>
        <span style={{ color: '#1976d2' }}>● Fact (사실)</span>
        <span style={{ color: '#f59f00' }}>● Event (타임라인)</span>
        <span style={{ color: '#e03131' }}>● LegalIssue (법률 쟁점)</span>
        <span style={{ color: '#2f9e44' }}>● Claim (추출 주장)</span>
        <span style={{ color: '#7950f2' }}>● Document (증거 문서)</span>
        <span style={{ color: '#868e96' }}>● Case (사건)</span>
      </div>
    </div>
  );
};
