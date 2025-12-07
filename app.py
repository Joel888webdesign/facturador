import React, { useState, useEffect } from 'react';
import { FileUpload } from './components/FileUpload';
import { InvoiceEditor } from './components/InvoiceEditor';
import { InvoicePreview } from './components/InvoicePreview';
import { SettingsSidebar } from './components/SettingsSidebar';
import { ProcessingStatus, InvoiceData, CompanySettings, Client } from './types';
import { extractInvoiceData } from './services/geminiService';
import { generateInvoicePDF } from './services/pdfGenerator';
import { Receipt, Sparkles, Settings, FileArchive, CheckCircle, AlertCircle, Loader2, Download } from 'lucide-react';
import JSZip from 'jszip';

const getMimeType = (file: File): string => {
  if (file.type) return file.type;
  
  const ext = file.name.split('.').pop()?.toLowerCase();
  switch (ext) {
    case 'pdf': return 'application/pdf';
    case 'jpg':
    case 'jpeg': return 'image/jpeg';
    case 'png': return 'image/png';
    case 'webp': return 'image/webp';
    case 'txt': return 'text/plain';
    case 'doc':
    case 'docx': return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
    case 'wps': return 'application/vnd.ms-works';
    default: return 'application/octet-stream';
  }
};

const DEFAULT_SETTINGS: CompanySettings = {
  name: '',
  cif: '',
  address: '',
  defaultTaxRate: 21,
  logo: null
};

const App: React.FC = () => {
  const [status, setStatus] = useState<ProcessingStatus>(ProcessingStatus.IDLE);
  const [invoiceData, setInvoiceData] = useState<InvoiceData | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  
  // Batch State
  const [batchMode, setBatchMode] = useState(false);
  const [batchQueue, setBatchQueue] = useState<File[]>([]);
  const [processedBatch, setProcessedBatch] = useState<InvoiceData[]>([]);
  const [batchProgress, setBatchProgress] = useState(0);
  const [batchVerified, setBatchVerified] = useState(false);

  // Settings & DB State
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState<CompanySettings>(DEFAULT_SETTINGS);
  const [clients, setClients] = useState<Client[]>([]);

  useEffect(() => {
    const savedSettings = localStorage.getItem('albaFacturaSettings');
    if (savedSettings) {
      try {
        setSettings(JSON.parse(savedSettings));
      } catch (e) {
        console.error("Error loading settings", e);
      }
    }

    const savedClients = localStorage.getItem('albaFacturaClients');
    if (savedClients) {
      try {
        setClients(JSON.parse(savedClients));
      } catch (e) {
        console.error("Error loading clients", e);
      }
    }
  }, []);

  const handleSaveSettings = (newSettings: CompanySettings) => {
    setSettings(newSettings);
    localStorage.setItem('albaFacturaSettings', JSON.stringify(newSettings));
  };

  const handleSaveClient = (client: Client) => {
    let newClients = [...clients];
    const index = newClients.findIndex(c => c.name.toLowerCase() === client.name.toLowerCase());
    
    if (index >= 0) {
      newClients[index] = client; 
    } else {
      newClients.push(client); 
    }

    setClients(newClients);
    localStorage.setItem('albaFacturaClients', JSON.stringify(newClients));
  };

  const processFile = async (file: File): Promise<InvoiceData> => {
      const reader = new FileReader();
      return new Promise((resolve, reject) => {
          reader.onload = async (e) => {
              const base64Data = e.target?.result as string;
              const base64Content = base64Data.split(',')[1];
              const mimeType = getMimeType(file);

              try {
                  const extractedData = await extractInvoiceData(base64Content, mimeType);
                  
                  // Apply Logic (Settings & Client DB)
                  if (settings.name) {
                      extractedData.supplierName = settings.name;
                      extractedData.supplierAddress = `${settings.address}\nCIF/NIF: ${settings.cif}`.trim();
                      extractedData.supplierLogo = settings.logo;
                      extractedData.taxRate = settings.defaultTaxRate;
                      
                      const subtotal = extractedData.items.reduce((acc, item) => acc + item.total, 0);
                      const taxAmount = Number((subtotal * (settings.defaultTaxRate / 100)).toFixed(2));
                      const total = Number((subtotal + taxAmount).toFixed(2));
                      
                      extractedData.subtotal = subtotal;
                      extractedData.taxAmount = taxAmount;
                      extractedData.total = total;
                  }

                  if (extractedData.clientName) {
                      const matchedClient = clients.find(c => 
                          c.name.toLowerCase().includes(extractedData.clientName.toLowerCase()) || 
                          extractedData.clientName.toLowerCase().includes(c.name.toLowerCase())
                      );
                      if (matchedClient) {
                          extractedData.clientName = matchedClient.name;
                          extractedData.clientAddress = matchedClient.address;
                          extractedData.clientCif = matchedClient.cif;
                      }
                  }
                  resolve(extractedData);
              } catch (err) {
                  reject(err);
              }
          };
          reader.readAsDataURL(file);
      });
  };

  const handleFileSelect = async (files: File[]) => {
    setErrorMsg(null);
    setBatchVerified(false);

    if (files.length === 1) {
        setBatchMode(false);
        setStatus(ProcessingStatus.UPLOADING);
        try {
            setStatus(ProcessingStatus.PROCESSING);
            const data = await processFile(files[0]);
            setInvoiceData(data);
            setStatus(ProcessingStatus.REVIEW);
        } catch (e) {
            console.error(e);
            setErrorMsg("Error procesando el archivo.");
            setStatus(ProcessingStatus.ERROR);
        }
    } else {
        // BATCH PROCESSING
        if (files.length > 10) {
            setErrorMsg("Máximo 10 archivos a la vez.");
            setStatus(ProcessingStatus.ERROR);
            return;
        }

        setBatchMode(true);
        setStatus(ProcessingStatus.PROCESSING);
        setBatchQueue(files);
        setProcessedBatch([]);
        setBatchProgress(0);

        const results: InvoiceData[] = [];
        
        // Process sequentially
        for (let i = 0; i < files.length; i++) {
            try {
                const data = await processFile(files[i]);
                results.push(data);
                setProcessedBatch([...results]);
                setBatchProgress(i + 1);
            } catch (e) {
                console.error(`Error processing file ${i}`, e);
                // Continue with others
            }
        }
        
        setStatus(ProcessingStatus.COMPLETED);
    }
  };

  const handleConfirmInvoice = () => {
    setStatus(ProcessingStatus.COMPLETED);
  };

  const handleCancel = () => {
    setStatus(ProcessingStatus.IDLE);
    setInvoiceData(null);
    setBatchMode(false);
    setProcessedBatch([]);
  };

  const handleNewInvoice = () => {
    setStatus(ProcessingStatus.IDLE);
    setInvoiceData(null);
    setBatchMode(false);
    setProcessedBatch([]);
  };

  const downloadBatchZip = async () => {
      const zip = new JSZip();
      
      processedBatch.forEach((data, index) => {
          const doc = generateInvoicePDF(data);
          // @ts-ignore
          const blob = doc.output('blob');
          const fileName = `Factura-${data.invoiceNumber || index + 1}.pdf`;
          zip.file(fileName, blob);
      });

      const content = await zip.generateAsync({ type: "blob" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(content);
      link.download = `Facturas_Lote_${new Date().toISOString().slice(0,10)}.zip`;
      link.click();
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Navbar */}
      <nav className="bg-white border-b border-gray-200 sticky top-0 z-50 print:hidden">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center gap-2">
              <div className="bg-blue-600 p-2 rounded-lg text-white">
                <Receipt size={24} />
              </div>
              <span className="font-bold text-xl text-gray-900 tracking-tight">AlbaFactura<span className="text-blue-600">AI</span></span>
            </div>
            <div className="flex items-center gap-4">
                <button 
                  onClick={() => setShowSettings(true)}
                  className="text-gray-500 hover:text-blue-600 hover:bg-blue-50 p-2 rounded-lg transition-colors flex items-center gap-2 text-sm font-medium"
                >
                  <Settings size={20} />
                  <span className="hidden sm:inline">Configuración</span>
                </button>
            </div>
          </div>
        </div>
      </nav>

      <SettingsSidebar 
        isOpen={showSettings} 
        onClose={() => setShowSettings(false)}
        settings={settings}
        onSave={handleSaveSettings}
      />

      {/* Main Content */}
      <main className="flex-grow p-6 md:p-12 relative">
        {status === ProcessingStatus.IDLE || status === ProcessingStatus.UPLOADING || status === ProcessingStatus.ERROR ? (
          <div className="flex flex-col items-center justify-center min-h-[60vh] space-y-8 animate-fade-in">
            <div className="text-center space-y-2 max-w-xl">
              <h1 className="text-4xl font-extrabold text-gray-900 tracking-tight">Convierte Albaranes en Facturas</h1>
              <p className="text-lg text-gray-600">
                Sube tus archivos.
                {settings.name ? (
                  <span className="text-blue-600 font-medium text-sm block mt-1">Empresa activa: {settings.name}</span>
                ) : (
                  <span className="text-gray-400 text-sm block mt-1">Configura tu empresa arriba.</span>
                )}
              </p>
            </div>

            <FileUpload onFileSelect={handleFileSelect} isProcessing={status === ProcessingStatus.UPLOADING} />

             {status === ProcessingStatus.ERROR && (
              <div className="bg-red-50 text-red-600 p-4 rounded-lg border border-red-200 max-w-md text-center">
                <p className="font-medium">Error</p>
                <p className="text-sm">{errorMsg}</p>
                <button onClick={() => setStatus(ProcessingStatus.IDLE)} className="mt-2 text-xs underline">Intentar de nuevo</button>
              </div>
            )}
          </div>
        ) : null}

        {/* BATCH PROCESSING PROGRESS */}
        {batchMode && status === ProcessingStatus.PROCESSING && (
            <div className="flex flex-col items-center justify-center min-h-[50vh] space-y-6">
                 <Loader2 size={48} className="text-blue-600 animate-spin" />
                 <h2 className="text-2xl font-bold text-gray-800">Procesando Lote...</h2>
                 <p className="text-gray-500">Analizando {batchProgress + 1} de {batchQueue.length} documentos</p>
                 <div className="w-full max-w-md bg-gray-200 rounded-full h-2.5">
                    <div 
                        className="bg-blue-600 h-2.5 rounded-full transition-all duration-300" 
                        style={{ width: `${(batchProgress / batchQueue.length) * 100}%` }}
                    ></div>
                 </div>
            </div>
        )}

        {/* BATCH RESULTS */}
        {batchMode && status === ProcessingStatus.COMPLETED && (
            <div className="max-w-4xl mx-auto animate-fade-in">
                <div className="bg-white rounded-xl shadow-xl overflow-hidden border border-gray-200">
                    <div className="p-6 border-b border-gray-100 bg-gray-50 flex justify-between items-center">
                        <div>
                            <h2 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                                <FileArchive className="text-blue-600" />
                                Resumen del Lote
                            </h2>
                            <p className="text-sm text-gray-500">Se han generado {processedBatch.length} facturas correctamente.</p>
                        </div>
                        <button onClick={handleNewInvoice} className="text-sm text-gray-500 hover:text-gray-700">
                           Empezar de nuevo
                        </button>
                    </div>
                    
                    <div className="divide-y divide-gray-100 max-h-[500px] overflow-y-auto">
                        {processedBatch.map((inv, idx) => (
                            <div key={idx} className="p-4 flex items-center justify-between hover:bg-gray-50">
                                <div className="flex items-center gap-4">
                                    <div className="bg-green-100 text-green-600 p-2 rounded-full">
                                        <CheckCircle size={18} />
                                    </div>
                                    <div>
                                        <p className="font-bold text-gray-800">Factura #{inv.invoiceNumber || '---'}</p>
                                        <p className="text-sm text-gray-500">{inv.clientName || 'Cliente desconocido'}</p>
                                    </div>
                                </div>
                                <div className="text-right">
                                    <p className="font-mono font-bold text-blue-600">€{inv.total.toFixed(2)}</p>
                                    <p className="text-xs text-gray-400">{inv.items.length} conceptos</p>
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="p-6 bg-gray-50 border-t border-gray-200 flex flex-col md:flex-row justify-between items-center gap-4">
                         <label className="flex items-center gap-2 cursor-pointer select-none bg-white px-4 py-2 rounded border border-gray-200 shadow-sm">
                            <input 
                                type="checkbox" 
                                checked={batchVerified}
                                onChange={(e) => setBatchVerified(e.target.checked)}
                                className="w-5 h-5 text-blue-600 rounded focus:ring-blue-500"
                            />
                            <span className="text-sm font-medium text-gray-700 flex items-center gap-2">
                                {!batchVerified && <AlertCircle size={16} className="text-orange-500" />}
                                He verificado que todos los datos son correctos
                            </span>
                        </label>

                        <button
                            onClick={downloadBatchZip}
                            disabled={!batchVerified}
                            className={`flex items-center gap-2 px-6 py-3 rounded-lg font-bold text-white shadow-md transition-all
                                ${batchVerified 
                                    ? 'bg-blue-600 hover:bg-blue-700 hover:shadow-lg transform hover:-translate-y-0.5' 
                                    : 'bg-gray-400 cursor-not-allowed opacity-70'
                                }
                            `}
                        >
                            <Download size={20} />
                            Descargar todo en ZIP
                        </button>
                    </div>
                </div>
            </div>
        )}

        {/* SINGLE MODE REVIEW */}
        {!batchMode && status === ProcessingStatus.REVIEW && invoiceData && (
          <InvoiceEditor 
            data={invoiceData} 
            clients={clients}
            onChange={setInvoiceData} 
            onConfirm={handleConfirmInvoice}
            onCancel={handleCancel}
            onSaveClient={handleSaveClient}
          />
        )}

        {/* SINGLE MODE COMPLETED */}
        {!batchMode && status === ProcessingStatus.COMPLETED && invoiceData && (
          <InvoicePreview 
            data={invoiceData} 
            onBack={() => setStatus(ProcessingStatus.REVIEW)}
            onNew={handleNewInvoice}
          />
        )}
      </main>
      
      <footer className="bg-white border-t border-gray-200 py-6 text-center print:hidden">
         <p className="text-sm text-gray-400">© {new Date().getFullYear()} AlbaFactura AI.</p>
      </footer>
    </div>
  );
};

export default App;
