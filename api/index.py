# /api/index.py
from flask import Flask, request, jsonify, render_template_string
import requests
import os

app = Flask(__name__)

# ============================================
# 🎨 FRONTEND: HTML + CSS + JS (Embedded)
# ============================================
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎵 TikTok Downloader - No Watermark</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        :root {
            --primary: #00f2fe;
            --secondary: #4facfe;
            --accent: #fe0091;
            --dark: #0a0a0f;
            --glass: rgba(255, 255, 255, 0.08);
            --glass-border: rgba(255, 255, 255, 0.15);
            --text: #ffffff;
            --text-muted: rgba(255, 255, 255, 0.6);
        }
        
        body {
            font-family: 'Inter', sans-serif;
            background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 50%, #16213e 100%);
            min-height: 100vh;
            color: var(--text);
            overflow-x: hidden;
            position: relative;
        }
        
        /* Animated Background */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: 
                radial-gradient(ellipse at 20% 80%, rgba(0, 242, 254, 0.15) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 20%, rgba(254, 0, 145, 0.15) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 50%, rgba(79, 172, 254, 0.1) 0%, transparent 70%);
            z-index: -1;
            animation: pulse 8s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .container {
            max-width: 680px;
            margin: 0 auto;
            padding: 40px 20px;
            position: relative;
            z-index: 1;
        }
        
        /* Header */
        header {
            text-align: center;
            padding: 30px 0;
            animation: fadeInDown 0.6s ease;
        }
        
        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .logo {
            font-size: 48px;
            margin-bottom: 12px;
            animation: bounce 2s infinite;
        }
        
        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-10px); }
        }
        
        h1 {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, var(--primary), var(--secondary), var(--accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            color: var(--text-muted);
            font-size: 15px;
            font-weight: 400;
        }
        
        /* Glassmorphism Card */
        .card {
            background: var(--glass);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            border-radius: 24px;
            padding: 32px;
            box-shadow: 
                0 8px 32px rgba(0, 0, 0, 0.3),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
            animation: fadeInUp 0.6s ease 0.2s both;
        }
        
        @keyframes fadeInUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* Input Section */
        .input-section {
            display: flex;
            gap: 12px;
            margin-bottom: 24px;
        }
        
        #urlInput {
            flex: 1;
            padding: 16px 20px;
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--glass-border);
            border-radius: 16px;
            color: var(--text);
            font-size: 15px;
            transition: all 0.3s ease;
            outline: none;
        }
        
        #urlInput::placeholder { color: var(--text-muted); }
        
        #urlInput:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(0, 242, 254, 0.2);
            background: rgba(255, 255, 255, 0.1);
        }
        
        #urlInput:hover { border-color: rgba(255, 255, 255, 0.3); }
        
        /* Neon Button */
        #downloadBtn {
            padding: 16px 28px;
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: #000;
            border: none;
            border-radius: 16px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s ease;
            box-shadow: 
                0 4px 15px rgba(0, 242, 254, 0.4),
                0 0 30px rgba(0, 242, 254, 0.2);
            white-space: nowrap;
        }
        
        #downloadBtn:hover {
            transform: translateY(-2px);
            box-shadow: 
                0 8px 25px rgba(0, 242, 254, 0.6),
                0 0 50px rgba(0, 242, 254, 0.4);
        }
        
        #downloadBtn:active { transform: translateY(0); }
        
        #downloadBtn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        /* Loading Spinner */
        .loading {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 16px;
            padding: 30px;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(255, 255, 255, 0.1);
            border-top-color: var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .loading p {
            color: var(--text-muted);
            font-size: 14px;
        }
        
        /* Error Message */
        .error {
            background: rgba(254, 0, 145, 0.15);
            border: 1px solid rgba(254, 0, 145, 0.4);
            border-radius: 12px;
            padding: 14px 18px;
            color: #ff6b9d;
            font-size: 14px;
            margin-bottom: 20px;
            animation: shake 0.5s ease;
        }
        
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-5px); }
            75% { transform: translateX(5px); }
        }
        
        /* Result Section */
        .result-section {
            animation: slideIn 0.4s ease;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .video-container {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 16px;
            overflow: hidden;
            margin-bottom: 20px;
            border: 1px solid var(--glass-border);
        }
        
        .video-container video {
            width: 100%;
            display: block;
            max-height: 400px;
            object-fit: contain;
            background: #000;
        }
        
        .download-btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, var(--accent), #ff4d8d);
            color: white;
            border: none;
            border-radius: 16px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: all 0.3s ease;
            box-shadow: 0 4px 20px rgba(254, 0, 145, 0.4);
        }
        
        .download-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(254, 0, 145, 0.6);
        }
        
        /* Utility */
        .hidden { display: none !important; }
        
        /* Footer */
        .footer {
            text-align: center;
            padding: 30px 20px 40px;
            color: var(--text-muted);
            font-size: 13px;
        }
        
        .footer a {
            color: var(--primary);
            text-decoration: none;
            transition: color 0.2s;
        }
        
        .footer a:hover { color: var(--secondary); }
        
        /* Responsive */
        @media (max-width: 600px) {
            .container { padding: 20px 16px; }
            .card { padding: 24px 20px; border-radius: 20px; }
            .input-section { flex-direction: column; }
            #downloadBtn { width: 100%; justify-content: center; }
            h1 { font-size: 24px; }
            .logo { font-size: 40px; }
        }
        
        /* Floating particles effect */
        .particle {
            position: fixed;
            width: 4px; height: 4px;
            background: var(--primary);
            border-radius: 50%;
            pointer-events: none;
            animation: float 6s ease-in-out infinite;
            opacity: 0.6;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(100vh) rotate(0deg); opacity: 0; }
            10% { opacity: 0.6; }
            90% { opacity: 0.6; }
            100% { transform: translateY(-100vh) rotate(720deg); opacity: 0; }
        }
    </style>
</head>
<body>
    <!-- Floating Particles -->
    <script>
        for(let i=0;i<15;i++){
            const p=document.createElement('div');
            p.className='particle';
            p.style.left=Math.random()*100+'%';
            p.style.animationDelay=Math.random()*6+'s';
            p.style.animationDuration=(4+Math.random()*4)+'s';
            document.body.appendChild(p);
        }
    </script>

    <div class="container">
        <header>
            <div class="logo">🎵</div>
            <h1>TikTok Video Downloader</h1>
            <p class="subtitle">Download video tanpa watermark • Gratis • Cepat • No Login</p>
        </header>
        
        <main class="card">
            <!-- Input Section -->
            <section class="input-section">
                <input type="url" id="urlInput" placeholder="🔗 Paste link TikTok di sini..." autocomplete="off">
                <button id="downloadBtn" onclick="downloadVideo()">
                    <span class="btn-text">Download</span>
                    <span class="btn-icon">↓</span>
                </button>
            </section>
            
            <!-- Loading -->
            <div id="loading" class="loading hidden">
                <div class="spinner"></div>
                <p>🔄 Memproses video...</p>
            </div>
            
            <!-- Error -->
            <div id="error" class="error hidden"></div>
            
            <!-- Result -->
            <section id="result" class="result-section hidden">
                <div class="video-container">
                    <video id="videoPreview" controls playsinline preload="metadata"></video>
                </div>
                <a id="downloadLink" class="download-btn" href="#" target="_blank" download>
                    <span>⬇️</span> Download Video Tanpa Watermark
                </a>
            </section>
        </main>
        
        <footer class="footer">
            <p>Made with ❤️ • Support: vt.tiktok.com • tiktok.com • Short links</p>
            <p style="margin-top:8px"><a href="#">Privacy</a> • <a href="#">Terms</a> • <a href="#">Contact</a></p>
        </footer>
    </div>
    
    <script>
        // Main download function
        async function downloadVideo() {
            const urlInput = document.getElementById('urlInput');
            const loading = document.getElementById('loading');
            const error = document.getElementById('error');
            const result = document.getElementById('result');
            const videoPreview = document.getElementById('videoPreview');
            const downloadLink = document.getElementById('downloadLink');
            const downloadBtn = document.getElementById('downloadBtn');
            
            const url = urlInput.value.trim();
            
            // Validation
            if (!url) {
                showError('⚠️ Silakan masukkan link TikTok terlebih dahulu');
                return;
            }
            
            if (!url.includes('tiktok.com')) {
                showError('❌ Link tidak valid. Gunakan link dari tiktok.com');
                return;
            }
            
            // Reset UI
            hideError();
            result.classList.add('hidden');
            loading.classList.remove('hidden');
            downloadBtn.disabled = true;
            
            try {
                const response = await fetch('/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                
                const data = await response.json();
                
                if (!response.ok) throw new Error(data.error || 'Gagal memproses video');
                if (!data.video) throw new Error('Video tidak ditemukan');
                
                // Success: Show preview & download
                videoPreview.src = data.video;
                downloadLink.href = data.video;
                result.classList.remove('hidden');
                
                // Smooth scroll to result
                setTimeout(() => {
                    result.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }, 100);
                
            } catch (err) {
                showError('❌ ' + err.message);
            } finally {
                loading.classList.add('hidden');
                downloadBtn.disabled = false;
            }
        }
        
        // Show error message
        function showError(message) {
            const error = document.getElementById('error');
            error.textContent = message;
            error.classList.remove('hidden');
            
            // Auto hide after 6 seconds
            setTimeout(() => error.classList.add('hidden'), 6000);
        }
        
        function hideError() {
            document.getElementById('error').classList.add('hidden');
        }
        
        // Enter key support
        document.getElementById('urlInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') downloadVideo();
        });
        
        // Input focus effects
        const urlInput = document.getElementById('urlInput');
        urlInput.addEventListener('focus', function() {
            this.parentElement.classList.add('focused');
        });
        urlInput.addEventListener('blur', function() {
            if (!this.value) this.parentElement.classList.remove('focused');
        });
    </script>
</body>
</html>
'''

# ============================================
# 🚀 FLASK ROUTES
# ============================================

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/download', methods=['POST'])
def download():
    """
    API Endpoint: POST /download
    Body: { "url": "https://vt.tiktok.com/xxx" }
    Response: { "video": "https://direct-video-url.mp4" }
    """
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL tidak boleh kosong'}), 400
        
        if 'tiktok.com' not in url:
            return jsonify({'error': 'Link harus dari domain tiktok.com'}), 400
        
        # Call TikTok Downloader API (tikwm.com - Free & No Watermark)
        api_endpoint = 'https://www.tikwm.com/api/'
        payload = {'url': url, 'hd': '1'}
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.post(api_endpoint, data=payload, headers=headers, timeout=30)
        result = response.json()
        
        # Parse response
        if result.get('code') == 0 and result.get('data'):
            video_data = result['data']
            # Prioritize HD, fallback to SD
            video_url = video_data.get('hdplay') or video_data.get('play')
            
            if video_url:
                return jsonify({'video': video_url})
            return jsonify({'error': 'Video tidak tersedia'}), 404
        else:
            error_msg = result.get('msg') or 'Gagal mengambil data video'
            return jsonify({'error': error_msg}), 400
            
    except requests.exceptions.Timeout:
        return jsonify({'error': '⏰ Request timeout. Silakan coba lagi.'}), 504
    except requests.exceptions.ConnectionError:
        return jsonify({'error': '🔌 Gagal terhubung ke server. Cek koneksi internet.'}), 502
    except Exception as e:
        return jsonify({'error': f'⚠️ Error: {str(e)}'}), 500

# ============================================
# ⚙️ VERCEL SERVERLESS CONFIG
# ============================================
if __name__ == '__main__':
    # Local development
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
else:
    # Production (Vercel)
    application = app
