import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listCases, createCase } from '../api/caseClient';
import type { CaseBase } from '../types/case';

export function CaseList() {
  const [cases, setCases] = useState<CaseBase[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    loadCases();
  }, []);

  const loadCases = async () => {
    try {
      const data = await listCases();
      setCases(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateCase = async () => {
    const title = prompt("새 사건의 제목을 입력하세요:", "주택임대차 분쟁 사건");
    if (!title) return;
    try {
      const newCase = await createCase(title, "주택임대차");
      navigate(`/${newCase.id}/workspace/overview`);
    } catch (e) {
      alert("사건 생성 실패");
    }
  };

  return (
    <div className="case-list">
      <h2>사건 목록</h2>
      <button onClick={handleCreateCase}>새 사건 생성</button>
      <ul>
        {cases.map(c => (
          <li key={c.id}>
            <strong>{c.title}</strong> ({c.status}) - {new Date(c.updated_at).toLocaleString()}
            <button onClick={() => navigate(`/${c.id}/workspace/overview`)}>열기</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

