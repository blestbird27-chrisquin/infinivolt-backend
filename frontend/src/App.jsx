import React, { useState, useRef } from 'react';

export default function App() {
  // --- Account State ---
  const [balance, setBalance] = useState(1500.00);
  const [transactions, setTransactions] = useState([]);

  // --- USSD State ---
  const [isUssdOpen, setIsUssdOpen] = useState(false);
  const [ussdInput, setUssdInput] = useState('');
  const [ussdResponse, setUssdResponse] = useState(
    '1. Airtime\n2. Data\n3. Prepaid\n4. Utility Bill\n5. Institutional Fees\n6. Toggle Active MoMo (024**763)'
  );
  const [ussdSessionId, setUssdSessionId] = useState(null);

  // --- Voice AI State ---
  const [language, setLanguage] = useState('en');
  const [isRecording, setIsRecording] = useState(false);
  const [recordingStatus, setRecordingStatus] = useState('');
  const [voiceResult, setVoiceResult] = useState(null);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);

  // --- Backend API Base URL (Configured for Local Network Access) ---
  const API_BASE = 'http://10.216.25.253:8000';

  // Helper to log transactions and deduct balance
  const logTransaction = (type, details, amount) => {
    if (amount && amount > 0) {
      setBalance((prev) => Math.max(0, prev - amount));
    }
    const newTx = {
      id: 'TX-' + Math.floor(1000 + Math.random() * 9000),
      type,
      details,
      amount: amount ? 'GHS ' + amount.toFixed(2) : 'N/A',
      time: new Date().toLocaleTimeString(),
    };
    setTransactions((prev) => [newTx, ...prev]);
  };

  // --- USSD Handler ---
  const handleUssdSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await fetch(API_BASE + '/api/ussd', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: ussdSessionId || ('session-' + Date.now()),
          phone_number: '0240000763',
          user_input: ussdInput,
        }),
      });
      const data = await response.json();
      const resMsg = data.message || data.response;
      setUssdResponse(resMsg);
      setUssdSessionId(data.session_id);

      if (data.amount_charged) {
        logTransaction('USSD Purchase', 'Input: ' + ussdInput, data.amount_charged);
      } else {
        logTransaction('USSD Menu', 'Input: ' + ussdInput, 0);
      }

      setUssdInput('');
    } catch (err) {
      setUssdResponse('🚨 Network Communication Failed. Check FastAPI backend status.');
    }
  };

  // --- Voice Recording Handlers ---
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        await sendAudioToBackend(audioBlob);
      };

      mediaRecorderRef.current.start();
      setIsRecording(true);
      setRecordingStatus('🎙️ Recording voice input... Speak now.');
      setVoiceResult(null);
    } catch (err) {
      alert('Microphone access denied or not available.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      setRecordingStatus('⏳ Processing voice recording with Khaya AI...');
    }
  };

  const sendAudioToBackend = async (blob) => {
    const formData = new FormData();
    formData.append('file', blob, 'recording.wav');

    try {
      const response = await fetch(
        API_BASE + '/api/voice/process?momo_number=0240000763&language=' + language,
        {
          method: 'POST',
          body: formData,
        }
      );
      const data = await response.json();

      if (data.task_id) {
        pollVoiceTaskStatus(data.task_id);
      } else {
        setRecordingStatus('❌ Failed to initiate voice processing.');
      }
    } catch (err) {
      setRecordingStatus('❌ Network Error: Could not connect to backend.');
    }
  };

  const pollVoiceTaskStatus = (taskId) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(API_BASE + '/api/voice/status/' + taskId);
        const statusData = await res.json();

        if (statusData.status === 'completed') {
          clearInterval(interval);
          setRecordingStatus('✅ Order Processed Successfully!');
          setVoiceResult(statusData);

          const charged = statusData.amount_charged || 0;
          logTransaction('Voice Order', statusData.transcript || 'Voice Command', charged);
        } else if (statusData.status === 'failed') {
          clearInterval(interval);
          setRecordingStatus('❌ Error: ' + (statusData.error || 'Task failed'));
        } else {
          setRecordingStatus('⏳ Status: ' + statusData.status + '...');
        }
      } catch (err) {
        clearInterval(interval);
        setRecordingStatus('❌ Error checking task status.');
      }
    }, 2000);
  };

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#0f172a', color: '#fff', padding: '2rem', fontFamily: 'sans-serif' }}>
      <div style={{ maxWidth: '650px', margin: '0 auto' }}>

        {/* Title Header */}
        <h1 style={{ fontSize: '2.5rem', fontWeight: 'bold', textAlign: 'center', marginBottom: '1.5rem' }}>
          InfiniVolt Hub
        </h1>

        {/* Balance Card */}
        <div style={{ backgroundColor: '#1e293b', padding: '1.5rem', borderRadius: '12px', marginBottom: '1.5rem', border: '1px solid #334155' }}>
          <h2 style={{ color: '#eab308', fontSize: '1.5rem', margin: 0 }}>
            Available Balance: GHS {balance.toFixed(2)}
          </h2>
          <p style={{ color: '#94a3b8', marginTop: '0.25rem' }}>Linked Target: 024**763</p>

          <button
            onClick={() => setIsUssdOpen(true)}
            style={{
              width: '100%',
              backgroundColor: '#eab308',
              color: '#000',
              fontWeight: 'bold',
              padding: '0.75rem',
              borderRadius: '8px',
              border: 'none',
              marginTop: '1rem',
              cursor: 'pointer'
            }}
          >
            Open Quick USSD (*2007#)
          </button>
        </div>

        {/* Voice AI Card */}
        <div style={{ backgroundColor: '#1e293b', padding: '1.5rem', borderRadius: '12px', marginBottom: '1.5rem', border: '1px solid #334155' }}>
          <h3 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span>🎤</span> Voice-Activated Purchase
          </h3>

          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', color: '#94a3b8', fontSize: '0.875rem', marginBottom: '0.5rem' }}>
              Select Ghanaian Language:
            </label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              style={{
                width: '100%',
                padding: '0.6rem',
                borderRadius: '6px',
                backgroundColor: '#0f172a',
                color: '#fff',
                border: '1px solid #475569'
              }}
            >
              <option value="en">English</option>
              <option value="tw">Twi</option>
              <option value="dag">Dagbani</option>
              <option value="ee">Ewe</option>
              <option value="ga">Ga</option>
            </select>
          </div>

          <button
            onClick={isRecording ? stopRecording : startRecording}
            style={{
              width: '100%',
              backgroundColor: isRecording ? '#ef4444' : '#22c55e',
              color: '#fff',
              fontWeight: 'bold',
              padding: '0.85rem',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '1rem',
              transition: 'all 0.2s'
            }}
          >
            {isRecording ? '⏹️ Stop Recording' : '🎙️ Tap to Record Voice'}
          </button>

          {recordingStatus && (
            <p style={{ marginTop: '1rem', fontSize: '0.9rem', color: '#cbd5e1', fontStyle: 'italic' }}>
              {recordingStatus}
            </p>
          )}

          {voiceResult && (
            <div style={{ marginTop: '1rem', padding: '1rem', backgroundColor: '#0f172a', borderRadius: '8px', border: '1px solid #22c55e' }}>
              <p style={{ color: '#22c55e', fontWeight: 'bold', margin: '0 0 0.5rem 0' }}>Result:</p>
              <p style={{ margin: '0 0 0.25rem 0' }}><strong>Transcript:</strong> "{voiceResult.transcript}"</p>
              <p style={{ margin: 0 }}><strong>Charged:</strong> GHS {voiceResult.amount_charged?.toFixed(2)}</p>
            </div>
          )}
        </div>

        {/* Recent Transactions Log */}
        <div style={{ backgroundColor: '#1e293b', padding: '1.5rem', borderRadius: '12px', border: '1px solid #334155' }}>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '1rem', color: '#94a3b8' }}>
            📋 Recent Transactions
          </h3>
          {transactions.length === 0 ? (
            <p style={{ color: '#64748b', fontSize: '0.9rem', margin: 0 }}>No transactions performed yet.</p>
          ) : (
            <table style={{ width: '100%', textAlign: 'left', borderCollapse: 'collapse', fontSize: '0.875rem' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #334155', color: '#cbd5e1' }}>
                  <th style={{ padding: '0.5rem 0' }}>Type</th>
                  <th style={{ padding: '0.5rem 0' }}>Details</th>
                  <th style={{ padding: '0.5rem 0' }}>Amount</th>
                  <th style={{ padding: '0.5rem 0', textAlign: 'right' }}>Time</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((tx) => (
                  <tr key={tx.id} style={{ borderBottom: '1px solid #1e293b' }}>
                    <td style={{ padding: '0.6rem 0', fontWeight: 'bold', color: '#4ade80' }}>{tx.type}</td>
                    <td style={{ padding: '0.6rem 0', color: '#94a3b8' }}>{tx.details}</td>
                    <td style={{ padding: '0.6rem 0', color: '#eab308' }}>{tx.amount}</td>
                    <td style={{ padding: '0.6rem 0', textAlign: 'right', color: '#64748b' }}>{tx.time}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* USSD Modal Overlay */}
        {isUssdOpen && (
          <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0,0,0,0.75)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', zIndex: 1000
          }}>
            <div style={{
              backgroundColor: '#052e16', border: '2px solid #22c55e',
              borderRadius: '12px', padding: '1.5rem', width: '90%',
              maxWidth: '450px', fontFamily: 'monospace', color: '#4ade80'
            }}>
              <div style={{ fontSize: '0.85rem', marginBottom: '0.5rem', borderBottom: '1px dashed #22c55e', paddingBottom: '0.5rem' }}>
                HUBTEL USSD: *2007# &nbsp;&nbsp; BAL: GHS {balance.toFixed(2)}
                <br />
                Target MoMo: 024**763
              </div>

              <pre style={{ whiteSpace: 'pre-wrap', margin: '1rem 0', fontSize: '1rem' }}>
                {ussdResponse}
              </pre>

              <form onSubmit={handleUssdSubmit}>
                <input
                  type="text"
                  placeholder="Enter number or custom input"
                  value={ussdInput}
                  onChange={(e) => setUssdInput(e.target.value)}
                  style={{
                    width: '100%', padding: '0.5rem', backgroundColor: 'transparent',
                    border: 'none', borderBottom: '2px solid #eab308', color: '#fff',
                    fontFamily: 'monospace', fontSize: '1rem', outline: 'none', boxSizing: 'border-box'
                  }}
                  autoFocus
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '1.5rem' }}>
                  <button
                    type="button"
                    onClick={() => setIsUssdOpen(false)}
                    style={{ backgroundColor: 'transparent', border: 'none', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}
                  >
                    EXIT
                  </button>
                  <button
                    type="submit"
                    style={{ backgroundColor: '#eab308', border: 'none', color: '#000', padding: '0.4rem 1.2rem', fontWeight: 'bold', borderRadius: '4px', cursor: 'pointer' }}
                  >
                    SEND
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}