import os
import json
import logging
from flask import render_template, request, redirect, url_for, flash, session, jsonify, send_file
from flask_login import current_user
from werkzeug.utils import secure_filename
from app import app, db
from models import SampleProject, AIProcessingLog
from replit_auth import require_login, make_replit_blueprint
from services.ai_orchestrator import AIOrchestrator
from services.audio_processor import AudioProcessor
from services.sonic_pi_generator import SonicPiGenerator
from services.mpc_integration import MPCWorkflowIntegrator, estimate_mpc_memory_usage

# Register authentication blueprint
app.register_blueprint(make_replit_blueprint(), url_prefix="/auth")

# Initialize services
ai_orchestrator = AIOrchestrator()
audio_processor = AudioProcessor()
sonic_pi_generator = SonicPiGenerator()
mpc_integrator = MPCWorkflowIntegrator()

# Make session permanent
@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route('/')
def index():
    """Landing page for logged out users, home page for logged in users"""
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('index.html')

@app.route('/home')
@require_login
def home():
    """Home page for authenticated users"""
    user_projects = SampleProject.query.filter_by(user_id=current_user.id).order_by(SampleProject.created_at.desc()).limit(10).all()
    return render_template('home.html', projects=user_projects)

@app.route('/upload', methods=['GET', 'POST'])
@require_login
def upload_file():
    """Upload MP3 file for reverse engineering to Sonic Pi"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Process the uploaded file
            try:
                # Analyze audio and generate Sonic Pi code
                description = request.form.get('description', '')
                project_name = request.form.get('project_name', filename)
                
                # Use AI orchestrator to analyze the file and generate code
                analysis_result = ai_orchestrator.analyze_audio_file(file_path, description)
                sonic_pi_code = sonic_pi_generator.generate_from_analysis(analysis_result)
                
                # Save project to database
                project = SampleProject(
                    user_id=current_user.id,
                    name=project_name,
                    description=description,
                    original_file_path=file_path,
                    sonic_pi_code=sonic_pi_code,
                    ai_models_used=json.dumps(analysis_result.get('models_used', []))
                )
                db.session.add(project)
                db.session.commit()
                
                flash('File processed successfully!', 'success')
                return redirect(url_for('view_project', project_id=project.id))
                
            except Exception as e:
                logging.error(f"Error processing file: {str(e)}")
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(request.url)
    
    return render_template('upload.html')

@app.route('/generate', methods=['GET', 'POST'])
@require_login
def generate_from_text():
    """Generate Sonic Pi code from text description"""
    if request.method == 'POST':
        description = request.form.get('description', '').strip()
        project_name = request.form.get('project_name', 'Untitled Project')
        
        if not description:
            flash('Please provide a description', 'error')
            return redirect(request.url)
        
        try:
            # Use AI orchestrator to generate code from description
            generation_result = ai_orchestrator.generate_from_description(description)
            sonic_pi_code = sonic_pi_generator.generate_from_description(generation_result)
            
            # Save project to database
            project = SampleProject(
                user_id=current_user.id,
                name=project_name,
                description=description,
                sonic_pi_code=sonic_pi_code,
                ai_models_used=json.dumps(generation_result.get('models_used', []))
            )
            db.session.add(project)
            db.session.commit()
            
            flash('Sonic Pi code generated successfully!', 'success')
            return redirect(url_for('view_project', project_id=project.id))
            
        except Exception as e:
            logging.error(f"Error generating code: {str(e)}")
            flash(f'Error generating code: {str(e)}', 'error')
            return redirect(request.url)
    
    return render_template('generate.html')

@app.route('/project/<int:project_id>')
@require_login
def view_project(project_id):
    """View a specific project"""
    project = SampleProject.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    return render_template('project.html', project=project)

@app.route('/project/<int:project_id>/download')
@require_login
def download_project(project_id):
    """Download Sonic Pi code as .rb file"""
    project = SampleProject.query.filter_by(id=project_id, user_id=current_user.id).first_or_404()
    
    # Create temporary file
    filename = f"{project.name.replace(' ', '_')}.rb"
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    
    with open(file_path, 'w') as f:
        f.write(project.sonic_pi_code)
    
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/api/voice-generate', methods=['POST'])
@require_login
def voice_generate():
    """Generate from voice input using speech recognition"""
    try:
        if 'audio' not in request.files:
            return jsonify({'error': 'No audio file provided'}), 400
        
        audio_file = request.files['audio']
        
        # Save temporary audio file
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], 'temp_voice.wav')
        audio_file.save(temp_path)
        
        # Transcribe audio using both Google API and Whisper
        transcription = ai_orchestrator.transcribe_audio(temp_path)
        
        # Generate Sonic Pi code from transcription
        generation_result = ai_orchestrator.generate_from_description(transcription)
        sonic_pi_code = sonic_pi_generator.generate_from_description(generation_result)
        
        # Clean up temp file
        os.remove(temp_path)
        
        return jsonify({
            'transcription': transcription,
            'sonic_pi_code': sonic_pi_code,
            'models_used': generation_result.get('models_used', [])
        })
        
    except Exception as e:
        logging.error(f"Error in voice generation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/youtube-search')
@require_login
def youtube_search():
    """Search YouTube using Google API"""
    query = request.args.get('q', '')
    if not query:
        return jsonify({'error': 'No search query provided'}), 400
    
    try:
        results = ai_orchestrator.search_youtube(query)
        return jsonify({'results': results})
    except Exception as e:
        logging.error(f"Error in YouTube search: {str(e)}")
        return jsonify({'error': str(e)}), 500

def allowed_file(filename):
    """Check if file extension is allowed"""
    ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.route('/mpc-convert', methods=['POST'])
@require_login
def mpc_convert():
    """Convert project for MPC-1 compatibility"""
    try:
        project_id = request.form.get('project_id')
        if not project_id:
            return jsonify({'error': 'Project ID required'}), 400
            
        project = SampleProject.query.get_or_404(project_id)
        if project.user_id != current_user.id:
            return jsonify({'error': 'Access denied'}), 403
            
        # Get sample files from project
        sample_files = []
        if project.original_file_path and os.path.exists(project.original_file_path):
            sample_files.append(project.original_file_path)
            
        # Process for MPC-1
        mpc_result = mpc_integrator.process_sonic_pi_for_mpc(
            project.sonic_pi_code,
            sample_files,
            project.name
        )
        
        if mpc_result['success']:
            return jsonify({
                'success': True,
                'package_path': mpc_result.get('package_path'),
                'program_file': mpc_result.get('program_file'),
                'converted_samples': len(mpc_result.get('converted_samples', [])),
                'memory_usage_kb': mpc_result.get('memory_usage', 0) / 1024,
                'instructions': mpc_result.get('mpc_instructions', [])
            })
        else:
            return jsonify({'error': mpc_result.get('error', 'MPC conversion failed')}), 500
            
    except Exception as e:
        logging.error(f"Error in MPC conversion: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/mpc-estimate', methods=['POST'])
@require_login
def mpc_estimate():
    """Estimate MPC-1 memory usage for uploaded files"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
            
        files = request.files.getlist('files')
        temp_files = []
        
        # Save uploaded files temporarily
        for file in files:
            if file and allowed_file(file.filename or ''):
                filename = secure_filename(file.filename or 'sample.wav')
                temp_path = os.path.join('uploads', f"temp_{filename}")
                file.save(temp_path)
                temp_files.append(temp_path)
        
        if not temp_files:
            return jsonify({'error': 'No valid audio files'}), 400
            
        # Estimate memory usage
        estimation = estimate_mpc_memory_usage(temp_files)
        
        # Clean up temp files
        for temp_file in temp_files:
            try:
                os.remove(temp_file)
            except:
                pass
                
        return jsonify({
            'success': True,
            'total_memory_kb': estimation['total_memory_kb'],
            'available_memory_kb': estimation['available_memory_kb'],
            'fits_in_base_memory': estimation['fits_in_base_memory'],
            'samples': estimation['samples']
        })
        
    except Exception as e:
        logging.error(f"Error in MPC estimation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/mpc-guide')
def mpc_guide():
    """Display MPC-1 integration guide"""
    return render_template('mpc_guide.html')

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500
