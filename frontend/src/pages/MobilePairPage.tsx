import React, { useState, useEffect } from 'react';
import { getMobilePairingInfo } from '../lib/api';
import { Smartphone, QrCode } from 'lucide-react';

export function MobilePairPage() {
  const [pairingUrl, setPairingUrl] = useState<string>('http://192.168.1.100:8000');
  const [qrCodeData, setQrCodeData] = useState<string | null>(null);

  useEffect(() => {
    getMobilePairingInfo().then(data => {
      if (data.url) setPairingUrl(data.url);
      if (data.qr_code) setQrCodeData(data.qr_code);
    }).catch(e => {
      // Dummy data fallback
    });
  }, []);

  return (
    <div className="p-6 max-w-4xl mx-auto flex flex-col items-center justify-center h-full text-center">
      <Smartphone size={48} className="mb-4" style={{ color: 'var(--color-accent)' }} />
      <h1 className="text-3xl font-bold mb-2">Mobile Companion</h1>
      <p className="mb-8 max-w-md" style={{ color: 'var(--color-text-secondary)' }}>
        Access NOVA AI on your phone by connecting to the local network URL below.
      </p>

      <div className="p-8 rounded-2xl mb-8 flex flex-col items-center bg-white shadow-sm border border-gray-100">
        {qrCodeData ? (
          <img src={qrCodeData} alt="QR Code" className="w-64 h-64 mb-6" />
        ) : (
          <div className="w-64 h-64 bg-gray-100 flex items-center justify-center rounded-xl mb-6">
            <QrCode size={48} className="text-gray-400" />
          </div>
        )}
        <div className="font-mono text-lg bg-gray-50 px-6 py-3 rounded-lg border text-gray-800">
          {pairingUrl}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full max-w-2xl text-left">
        <div className="p-5 rounded-xl border" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
          <h3 className="font-semibold mb-2">iOS (iPhone)</h3>
          <ol className="list-decimal pl-5 text-sm space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
            <li>Open the camera app</li>
            <li>Scan the QR code</li>
            <li>Tap the link to open in Safari</li>
            <li>Tap Share icon, then "Add to Home Screen"</li>
          </ol>
        </div>
        <div className="p-5 rounded-xl border" style={{ background: 'var(--color-bg-secondary)', borderColor: 'var(--color-border)' }}>
          <h3 className="font-semibold mb-2">Android</h3>
          <ol className="list-decimal pl-5 text-sm space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
            <li>Open your QR scanner or Camera app</li>
            <li>Scan the QR code to open Chrome</li>
            <li>Tap the 3 dots menu</li>
            <li>Select "Install app" or "Add to Home screen"</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
