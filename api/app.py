from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from markupsafe import Markup, escape
from dotenv import load_dotenv
import os
import secrets
import pymysql
from datetime import datetime
from PIL import Image
import folium
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError, ClientError

load_dotenv()
app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)

# Credenciais e Configurações AWS S3
S3_BUCKET = os.getenv('S3_BUCKET_NAME')
S3_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY_ID')
S3_SECRET_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
S3_REGION = os.getenv('AWS_REGION')

s3_client = None
if S3_BUCKET and S3_ACCESS_KEY and S3_SECRET_KEY and S3_REGION:
    try:
        s3_client = boto3.client(
            's3',
            aws_access_key_id=S3_ACCESS_KEY,
            aws_secret_access_key=S3_SECRET_KEY,
            region_name=S3_REGION
        )
        app.logger.info(f"Cliente S3 inicializado para o bucket {S3_BUCKET} na região {S3_REGION}")
    except Exception as e:
        app.logger.error(f"Erro ao inicializar cliente S3: {e}")
else:
    app.logger.warning("Credenciais S3 ou nome do bucket não configurados. Uploads para S3 estarão desabilitados.")


# Configurações de Upload
TMP_UPLOAD_DIR = '/tmp/buscapet_uploads' # Diretório temporário na Vercel
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
THUMBNAIL_SIZE = (100, 100) # Tamanho do thumbnail


# Função para criar diretório temporário se não existir
def ensure_tmp_upload_dir():
    original_tmp = os.path.join(TMP_UPLOAD_DIR, 'imagens_pet')
    thumbnail_tmp = os.path.join(TMP_UPLOAD_DIR, 'thumbnails_pet')
    os.makedirs(original_tmp, exist_ok=True)
    os.makedirs(thumbnail_tmp, exist_ok=True)
    return original_tmp, thumbnail_tmp


# Registrar filtro nl2br customizado
@app.template_filter('nl2br')
def nl2br_filter(s):
    if s:
        # Escapa o HTML e depois substitui \n por <br>
        # Usar Markup para dizer ao Jinja que a string resultante é segura para renderizar como HTML
        return Markup(escape(s).replace('\n', '<br>\n'))
    return ''

# Função para verificar extensão permitida
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Função de conexão com o banco (adaptada do seu exemplo)
def open_conn():
    conn = None
    try:
        conn = pymysql.connect(
            charset="utf8mb4",
            connect_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
            db=os.getenv('MYSQL_DB'),
            host=os.getenv('MYSQL_HOST'),
            password=os.getenv('MYSQL_PASSWORD'),
            read_timeout=30,
            port=int(os.getenv('MYSQL_PORT', 3306)), # Default para MySQL padrão, caso não especificado
            user=os.getenv('MYSQL_USER'),
            write_timeout=30,
        )
        return conn
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao conectar ao MySQL: {e}")
        # Em um app real, você poderia tentar reconectar ou levantar uma exceção mais específica
        # Para este exemplo, retornamos None e as rotas devem tratar isso
        return None
    except Exception as ex:
        app.logger.error(f"Erro geral na conexão com DB: {ex}")
        return None


def create_thumbnail(image_path, thumbnail_path, size=THUMBNAIL_SIZE):
    try:
        with Image.open(image_path) as img: # Usar 'with' para garantir fechamento do arquivo
            img.thumbnail(size)
            img.save(thumbnail_path)
        return True
    except FileNotFoundError:
        app.logger.error(f"Arquivo de imagem não encontrado em create_thumbnail: {image_path}")
    except Exception as e:
        app.logger.error(f"Erro ao criar thumbnail para {image_path}: {e}")
    return False


def upload_to_s3(file_path, bucket_name, s3_file_key, content_type=None):
    """Faz upload de um arquivo para um bucket S3 e o torna público."""
    if not s3_client:
        app.logger.error("Cliente S3 não inicializado. Upload falhou.")
        return None
    try:
        extra_args = {}
        if content_type:
            extra_args['ContentType'] = content_type
        s3_client.upload_file(file_path, bucket_name, s3_file_key, ExtraArgs=extra_args)
        # URL do objeto no S3
        file_url = f"https://{bucket_name}.s3.{S3_REGION}.amazonaws.com/{s3_file_key}"
        app.logger.info(f"Upload bem-sucedido para S3: {file_url}")
        return file_url
    except FileNotFoundError:
        app.logger.error(f"Arquivo não encontrado para upload S3: {file_path}")
    except NoCredentialsError:
        app.logger.error("Credenciais AWS não encontradas para upload S3.")
    except PartialCredentialsError:
        app.logger.error("Credenciais AWS incompletas para upload S3.")
    except ClientError as e:
        # Verifica se o erro é especificamente sobre ACLs não suportadas
        if e.response.get('Error', {}).get('Code') == 'AccessControlListNotSupported':
            app.logger.error(f"Erro ao fazer upload para S3 (AccessControlListNotSupported): {e}. "
                             "Verifique as configurações de 'Object Ownership' do bucket. "
                             "Se ACLs estão desabilitadas, remova a configuração de ACL no upload.")
        else:
            app.logger.error(f"Erro do cliente S3 durante o upload: {e}")
    except Exception as e:
        app.logger.error(f"Erro inesperado durante o upload para S3: {e}")
    return None

def delete_from_s3(bucket_name, s3_file_key):
    """Deleta um arquivo de um bucket S3."""
    if not s3_client:
        app.logger.error("Cliente S3 não inicializado. Deleção falhou.")
        return False
    if not s3_file_key: # Não tentar deletar se a chave for None ou vazia
        app.logger.warning(f"Chave S3 vazia ou None, deleção ignorada.")
        return True # Considerar como sucesso se não há nada para deletar
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=s3_file_key)
        app.logger.info(f"Deleção bem-sucedida do S3: s3://{bucket_name}/{s3_file_key}")
        return True
    except ClientError as e:
        app.logger.error(f"Erro do cliente S3 durante a deleção: {e}")
    except Exception as e:
        app.logger.error(f"Erro inesperado durante a deleção do S3: {e}")
    return False

@app.route('/')
def principal():
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados.", "danger")
        return render_template('index.html', current_year=datetime.now().year, mapa_html=None)

    mapa_folium = None
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT ID, NOME_PET, ESPECIE, BAIRRO, STATUS_PET, THUMBNAIL_PATH, LATITUDE, LONGITUDE
                FROM USERINPUT 
                WHERE RESOLVIDO = 0 OR RESOLVIDO IS NULL 
                ORDER BY CREATED_AT DESC
            """
            cursor.execute(sql)
            pets_no_mapa = cursor.fetchall()

        if pets_no_mapa:
            avg_lat = sum(p['LATITUDE'] for p in pets_no_mapa if p.get('LATITUDE')) / len([p for p in pets_no_mapa if p.get('LATITUDE')]) if any(p.get('LATITUDE') for p in pets_no_mapa) else -22.7532
            avg_lon = sum(p['LONGITUDE'] for p in pets_no_mapa if p.get('LONGITUDE')) / len([p for p in pets_no_mapa if p.get('LONGITUDE')]) if any(p.get('LONGITUDE') for p in pets_no_mapa) else -47.3330
            
            mapa_folium = folium.Map(location=[avg_lat, avg_lon], zoom_start=13, tiles="CartoDB positron")

            for pet in pets_no_mapa:
                if pet.get('LATITUDE') and pet.get('LONGITUDE') and pet.get('THUMBNAIL_PATH'):
                    
                    detalhes_pet_url = url_for('detalhes_pet', pet_id=pet['ID'], _external=True)
                    status_pet_mapa = pet.get('STATUS_PET', 'Perdi meu PET')
                    
                    thumbnail_s3_key = pet.get('THUMBNAIL_PATH')
                    thumbnail_url_para_icone = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{thumbnail_s3_key}" if thumbnail_s3_key and S3_BUCKET and S3_REGION else '#'
                    
                    icon_border_color = "red"
                    if status_pet_mapa == "Encontrei um PET":
                        icon_border_color = "green"
                    
                    icon_html = f"""
                    <div style="
                        width: 52px; height: 52px; border-radius: 50%;
                        background-color: {icon_border_color}; display: flex;
                        justify-content: center; align-items: center;
                        box-shadow: 0px 0px 5px rgba(0,0,0,0.5); padding: 2px;">
                        <img src="{thumbnail_url_para_icone}" alt="T" 
                             style="width: 48px; height: 48px; border-radius: 50%; object-fit: cover;">
                    </div>
                    """
                    custom_map_icon = folium.DivIcon(
                        icon_size=(52, 52),
                        icon_anchor=(26, 52),
                        html=icon_html
                    )
                    
                    popup_html_content = f"""
                    <div style="font-family: 'Nunito', sans-serif; text-align:center; min-width:180px; padding: 10px;">
                        <strong style="font-size: 1.1em; color: #2D3748;">{pet.get('NOME_PET', 'Pet')}</strong><br>
                        <span style="font-size: 0.9em; color: #6A7588;">({pet.get('ESPECIE', '')})</span><br>
                        <a href="{detalhes_pet_url}" target="_blank" class="popup-details-link"> 
                           Ver Detalhes do PET
                        </a>
                    </div>
                    """
                    popup_styles = """
                    <style>
                        body { margin:0; font-family: 'Nunito', sans-serif; }
                        .popup-details-link {
                            display: inline-block; margin-top: 8px; padding: 6px 12px;
                            background-color: #4A90E2; color: white !important; text-decoration: none;
                            border-radius: 20px; font-weight: 600; font-size: 0.9em;
                            transition: background-color 0.2s ease;
                        }
                        .popup-details-link:hover { background-color: #357ABD; }
                    </style>
                    """
                    full_popup_html = popup_styles + popup_html_content
                    
                    iframe = folium.IFrame(full_popup_html, width=220, height=110)
                    popup = folium.Popup(iframe, max_width=220)
                    
                    marker = folium.Marker(
                        location=[pet['LATITUDE'], pet['LONGITUDE']],
                        icon=custom_map_icon,
                        tooltip=f"<strong>{pet.get('NOME_PET', 'Pet')}</strong><br>Status: {status_pet_mapa}<br>Clique para mais informações"
                    )
                    marker.add_child(popup)
                    marker.add_to(mapa_folium)

            mapa_html = mapa_folium._repr_html_() if mapa_folium else "<p class='text-center alert alert-info'>Nenhum pet perdido para exibir no mapa no momento.</p>"
        else:
            mapa_folium = folium.Map(location=[-22.7532, -47.3330], zoom_start=12, tiles="CartoDB positron")
            mapa_html = mapa_folium._repr_html_()
            if not app.debug: # Não mostrar flash se for só o mapa vazio em debug
                 flash("Nenhum pet cadastrado como perdido ou encontrado no momento.", "info")
            
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar pets para o mapa: {e}")
        flash("Erro ao carregar dados dos pets.", "danger")
        mapa_html = "<p class='text-center alert alert-danger'>Erro ao carregar o mapa. Tente novamente mais tarde.</p>"
    except Exception as e_geral: # Captura outros erros inesperados
        app.logger.error(f"Erro geral na rota principal: {e_geral}")
        flash("Ocorreu um erro inesperado ao carregar a página principal.", "danger")
        # Retorna um mapa vazio em caso de erro não previsto para não quebrar a página
        mapa_folium_erro = folium.Map(location=[-22.7532, -47.3330], zoom_start=12, tiles="CartoDB positron")
        mapa_html = mapa_folium_erro._repr_html_()
    finally:
        if conn:
            conn.close()
            
    return render_template('index.html', 
                           current_year=datetime.now().year, 
                           mapa_html=mapa_html)


@app.route('/pet/<int:pet_id>')
def detalhes_pet(pet_id):
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados.", "danger")
        return redirect(url_for('principal'))

    pet_info = None
    latest_messages = []
    try:
        with conn.cursor() as cursor:
            sql_pet = """
                SELECT ID, NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                       FOTO_PATH, THUMBNAIL_PATH, CREATED_AT, STATUS_PET, RESOLVIDO, RESOLVIDO_AT 
                FROM USERINPUT 
                WHERE ID = %s
            """ # Adicionado THUMBNAIL_PATH e RESOLVIDO_AT se precisar
            cursor.execute(sql_pet, (pet_id,))
            pet_info = cursor.fetchone()

            if pet_info:
                sql_messages = """
                    SELECT MessageID, CommenterName, MessageText, CreatedAt
                    FROM MESSAGES
                    WHERE PetID = %s
                    ORDER BY CreatedAt DESC
                    LIMIT 3 
                """
                cursor.execute(sql_messages, (pet_id,))
                latest_messages = cursor.fetchall()
            else: # Pet não encontrado
                flash("Pet não encontrado.", "warning")
                return redirect(url_for('principal'))

    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar detalhes do pet ID {pet_id}: {e}")
        flash("Erro ao carregar informações do pet.", "danger")
        return redirect(url_for('principal'))
    finally:
        if conn:
            conn.close()

    # Se pet_info ainda for None aqui, significa que o pet não foi encontrado (já tratado acima)
    # Mas por segurança, adicionamos uma verificação, embora o redirect já devesse ter ocorrido.
    if not pet_info:
         # Este flash pode ser redundante se o de cima já foi acionado
        flash("Informações do pet não puderam ser carregadas.", "danger")
        return redirect(url_for('principal'))


    foto_s3_key = pet_info.get('FOTO_PATH')
    foto_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{foto_s3_key}" if foto_s3_key and S3_BUCKET and S3_REGION else '#'
        
    url_encerrar = url_for('confirmar_encerrar_busca', pet_id=pet_info['ID'])

    status_pet_classe = "status-perdi-text" 
    if pet_info.get('RESOLVIDO'):
        status_pet_classe = "status-resolvido-text"
    elif pet_info.get('STATUS_PET') == "Encontrei um PET":
        status_pet_classe = "status-encontrado-text"

    return render_template('detalhes_pet.html', 
                           pet=pet_info, 
                           foto_url=foto_url,
                           url_encerrar=url_encerrar,
                           status_classe=status_pet_classe,
                           messages=latest_messages,
                           current_year=datetime.now().year)


@app.route('/encerrar_busca/<int:pet_id>', methods=['POST'])
def encerrar_busca(pet_id):
    conn = open_conn()
    if not conn:
        return jsonify({"success": False, "message": "Erro de conexão com o banco."})
    try:
        with conn.cursor() as cursor:
            sql = "UPDATE USERINPUT SET RESOLVIDO = 1, RESOLVIDO_AT = %s WHERE ID = %s AND (RESOLVIDO = 0 OR RESOLVIDO IS NULL)"
            affected_rows = cursor.execute(sql, (datetime.now(), pet_id))
            conn.commit()
        if affected_rows > 0:
            return jsonify({"success": True, "message": "Busca encerrada com sucesso!"})
        else:
            return jsonify({"success": False, "message": "Pet não encontrado ou busca já encerrada."})
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao encerrar busca para pet ID {pet_id}: {e}")
        return jsonify({"success": False, "message": "Erro ao atualizar o banco de dados."})
    finally:
        if conn:
            conn.close()

@app.route('/cadastrar-pet', methods=['GET', 'POST'])
def cadastrar_pet():
    # Tenta abrir a conexão para buscar bairros, mas apenas se for GET
    # Para POST, a conexão será aberta dentro do bloco de processamento se necessário
    conn_for_bairros = None
    if request.method == 'GET':
        conn_for_bairros = open_conn()
        if not conn_for_bairros:
            flash("Erro de conexão com o banco de dados. Não é possível carregar os bairros.", "danger")
            # Mesmo com erro, renderiza o template para o usuário ver a mensagem
            return render_template('cadastrar_pet.html', bairros=[]) 

    bairros = []
    if conn_for_bairros: # Se a conexão foi bem-sucedida para GET
        try:
            with conn_for_bairros.cursor() as cursor:
                cursor.execute("SELECT DISTINCT BAIRRO FROM LOCATIONS ORDER BY BAIRRO ASC;")
                bairros_data = cursor.fetchall()
                bairros = [row['BAIRRO'] for row in bairros_data]
        except pymysql.MySQLError as e:
            app.logger.error(f"Erro ao buscar bairros: {e}")
            flash("Erro ao carregar lista de bairros.", "danger")
        finally:
            conn_for_bairros.close()

    if request.method == 'POST':
        # Obter dados do formulário
        nome_pet = request.form.get('nome_pet')
        especie = request.form.get('especie')
        rua = request.form.get('rua')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade', 'Americana/SP')
        contato = request.form.get('contato')
        comentario = request.form.get('comentario')
        status_pet = request.form.get('status_pet', 'Perdi meu PET')

        # Validação do arquivo
        if 'foto_pet' not in request.files or not request.files['foto_pet'].filename:
            flash('Nenhuma foto selecionada ou arquivo inválido!', 'danger')
            return render_template('cadastrar_pet.html', bairros=bairros) # Re-renderiza com bairros
        
        file = request.files['foto_pet']

        if not (file and allowed_file(file.filename)):
            flash('Tipo de arquivo não permitido!', 'danger')
            return render_template('cadastrar_pet.html', bairros=bairros)

        # Gerar nomes de arquivo e caminhos
        # Adicionar microssegundos para maior unicidade em caso de uploads rápidos
        filename_base = secure_filename(file.filename)
        timestamp_str = datetime.now().strftime('%Y%m%d%H%M%S%f') 
        unique_filename = f"{timestamp_str}_{filename_base}"
        
        original_tmp_dir, thumbnail_tmp_dir = ensure_tmp_upload_dir()

        temp_original_filepath = os.path.join(original_tmp_dir, unique_filename)
        temp_thumbnail_filename = f"thumb_{unique_filename}"
        temp_thumbnail_filepath = os.path.join(thumbnail_tmp_dir, temp_thumbnail_filename)

        # Definir chaves S3
        s3_original_key = f"uploads/imagens_pet/{unique_filename}"
        s3_thumbnail_key = f"uploads/thumbnails_pet/{temp_thumbnail_filename}"
        
        foto_url_s3 = None
        thumbnail_url_s3 = None

        try:
            file.save(temp_original_filepath) # Salva no /tmp primeiro
            
            if create_thumbnail(temp_original_filepath, temp_thumbnail_filepath):
                # Upload para S3
                content_type = file.content_type or 'application/octet-stream' # Default content type
                
                app.logger.info(f"Tentando upload da imagem original para S3: {s3_original_key}")
                foto_url_s3 = upload_to_s3(temp_original_filepath, S3_BUCKET, s3_original_key, content_type=content_type)
                
                app.logger.info(f"Tentando upload do thumbnail para S3: {s3_thumbnail_key}")
                thumbnail_url_s3 = upload_to_s3(temp_thumbnail_filepath, S3_BUCKET, s3_thumbnail_key, content_type=content_type)

                if not (foto_url_s3 and thumbnail_url_s3):
                    flash('Erro ao fazer upload das imagens para o armazenamento na nuvem. Tente novamente.', 'danger')
                    # Limpeza no S3 se um upload falhou e o outro não
                    if foto_url_s3: delete_from_s3(S3_BUCKET, s3_original_key)
                    if thumbnail_url_s3: delete_from_s3(S3_BUCKET, s3_thumbnail_key)
                    raise Exception("Falha no upload para o S3") # Força o bloco except abaixo

                # Obter coordenadas da tabela LOCATIONS
                lat, lon = None, None
                conn_coords = open_conn() # Nova conexão para buscar coordenadas
                if conn_coords:
                    try:
                        if bairro and rua:
                            with conn_coords.cursor() as cursor_coords:
                                sql_coords = "SELECT LATITUDE, LONGITUDE FROM LOCATIONS WHERE BAIRRO = %s AND RUA = %s LIMIT 1"
                                cursor_coords.execute(sql_coords, (bairro, rua))
                                coords_data = cursor_coords.fetchone()
                                if coords_data:
                                    lat, lon = coords_data['LATITUDE'], coords_data['LONGITUDE']
                                else:
                                    flash(f'Coordenadas não encontradas para {rua}, {bairro}. O pet será cadastrado sem geolocalização precisa no mapa.', 'warning')
                        else:
                            flash('Bairro ou rua não fornecidos para busca de coordenadas.', 'warning')
                    except pymysql.MySQLError as e_coords:
                        app.logger.error(f"Erro ao buscar coordenadas: {e_coords}")
                        flash('Erro ao obter coordenadas. O pet será cadastrado sem geolocalização precisa.', 'warning')
                    finally:
                        conn_coords.close()
                else:
                    flash('Não foi possível conectar ao banco para buscar coordenadas.', 'warning')


                # Salvar no banco de dados as CHAVES S3
                conn_db_insert = open_conn()
                if conn_db_insert:
                    try:
                        with conn_db_insert.cursor() as cursor_insert:
                            sql_insert = """
                                INSERT INTO USERINPUT 
                                (NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                                 FOTO_PATH, THUMBNAIL_PATH, CREATED_AT, RESOLVIDO, LATITUDE, LONGITUDE,
                                 STATUS_PET)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s)
                            """
                            cursor_insert.execute(sql_insert, 
                                                (nome_pet, especie, rua, bairro, cidade, contato, comentario,
                                                s3_original_key, s3_thumbnail_key, datetime.now(), lat, lon,
                                                status_pet))
                            conn_db_insert.commit()
                            flash('Pet cadastrado com sucesso!', 'success')
                            # Limpar arquivos temporários somente após tudo dar certo
                            if os.path.exists(temp_original_filepath): os.remove(temp_original_filepath)
                            if os.path.exists(temp_thumbnail_filepath): os.remove(temp_thumbnail_filepath)
                            return redirect(url_for('principal'))
                    except pymysql.MySQLError as e_db:
                        app.logger.error(f"Erro ao inserir pet no banco: {e_db}")
                        flash(f'Erro ao salvar dados no banco: {e_db}', 'danger')
                        conn_db_insert.rollback()
                        # Se falhar ao salvar no DB, deletar do S3 para manter consistência
                        if foto_url_s3: delete_from_s3(S3_BUCKET, s3_original_key)
                        if thumbnail_url_s3: delete_from_s3(S3_BUCKET, s3_thumbnail_key)
                    finally:
                        conn_db_insert.close()
                else: # Falha ao conectar para inserir no DB
                     flash('Erro de conexão com o banco ao tentar salvar o pet.', 'danger')
                     if foto_url_s3: delete_from_s3(S3_BUCKET, s3_original_key)
                     if thumbnail_url_s3: delete_from_s3(S3_BUCKET, s3_thumbnail_key)

            else: # Falha ao criar thumbnail
                flash('Erro ao processar a imagem (não foi possível criar miniatura).', 'danger')
        
        except Exception as e_file_proc: # Captura erros de file.save, create_thumbnail, S3 uploads
            app.logger.error(f"Erro no processamento do arquivo ou upload S3: {e_file_proc}")
            flash(f'Ocorreu um erro ao processar o arquivo da foto: {e_file_proc}', 'danger')
        finally: 
            # Garantir limpeza dos arquivos temporários em caso de qualquer erro no try principal
            if 'temp_original_filepath' in locals() and os.path.exists(temp_original_filepath):
                try: os.remove(temp_original_filepath)
                except OSError as e_os_remove: app.logger.error(f"Erro ao remover temp original: {e_os_remove}")
            if 'temp_thumbnail_filepath' in locals() and os.path.exists(temp_thumbnail_filepath):
                try: os.remove(temp_thumbnail_filepath)
                except OSError as e_os_remove: app.logger.error(f"Erro ao remover temp thumbnail: {e_os_remove}")
        
        # Se chegou aqui após um erro no POST, re-renderiza o formulário com mensagens e bairros
        return render_template('cadastrar_pet.html', bairros=bairros)

    # Para GET request, apenas renderiza o formulário com a lista de bairros
    return render_template('cadastrar_pet.html', bairros=bairros)

@app.route('/buscar_ruas_por_bairro')
def buscar_ruas_por_bairro():
    bairro = request.args.get('bairro')
    conn = open_conn()
    if not conn:
        return jsonify([]) # Retorna lista vazia se não houver conexão
    
    ruas = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT RUA FROM LOCATIONS WHERE BAIRRO = %s ORDER BY RUA ASC", (bairro,))
            ruas_data = cursor.fetchall()
            ruas = [row['RUA'] for row in ruas_data]
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar ruas para o bairro {bairro}: {e}")
    finally:
        if conn:
            conn.close()
    return jsonify(ruas)


# --- Funções e rota do Dashboard (adaptadas do seu exemplo) ---
def gerar_dados_dashboard_pets():
    conn = open_conn()
    if not conn: return None, None, None, None, True # sem_dados = True

    latest_cases, stats_chart, sem_dados = None, None, True
    
    try:
        with conn.cursor() as cursor:
            # Total de pets perdidos (não resolvidos)
            cursor.execute("SELECT COUNT(*) as total FROM USERINPUT WHERE RESOLVIDO = 0 OR RESOLVIDO IS NULL")
            total_perdidos = cursor.fetchone()['total']

            # Total de pets encontrados (resolvidos)
            cursor.execute("SELECT COUNT(*) as total FROM USERINPUT WHERE RESOLVIDO = 1")
            total_encontrados = cursor.fetchone()['total']

            # Top 5 bairros com mais pets perdidos
            cursor.execute("""
                SELECT BAIRRO, COUNT(*) as count 
                FROM USERINPUT 
                WHERE (RESOLVIDO = 0 OR RESOLVIDO IS NULL) AND BAIRRO IS NOT NULL
                GROUP BY BAIRRO 
                ORDER BY count DESC 
                LIMIT 5
            """)
            top_bairros_perdidos = cursor.fetchall()

            # Dados para WordCloud (usar nomes dos pets ou comentários)
            cursor.execute("SELECT COMENTARIO FROM USERINPUT WHERE (RESOLVIDO = 0 OR RESOLVIDO IS NULL) AND COMENTARIO IS NOT NULL")
            comentarios_data = cursor.fetchall()
            
            # Últimos 5 casos cadastrados (não resolvidos)
            cursor.execute("""
                SELECT NOME_PET, ESPECIE, BAIRRO, CREATED_AT 
                FROM USERINPUT 
                WHERE (RESOLVIDO = 0 OR RESOLVIDO IS NULL)
                ORDER BY CREATED_AT DESC LIMIT 5
            """)
            latest_cases = cursor.fetchall()
        
        # Gráfico de Estatísticas (Ex: Perdidos vs Encontrados)
        if total_perdidos > 0 or total_encontrados > 0:
            sem_dados = False
            labels = ['Perdidos Atualmente', 'Encontrados']
            sizes = [total_perdidos, total_encontrados]
            colors = ['#ff9999','#66b3ff']
            
            _, ax = plt.subplots(figsize=(5,3)) # Ajustar tamanho
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, colors=colors)
            ax.axis('equal') # Equal aspect ratio ens.
            
            buffer = BytesIO()
            plt.savefig(buffer, format='png', transparent=True, bbox_inches='tight')
            buffer.seek(0)
            stats_chart = base64.b64encode(buffer.getvalue()).decode('utf-8')
            plt.clf()

        # Montar um dict com os dados do dashboard
        dashboard_data = {
            "total_perdidos": total_perdidos,
            "total_encontrados": total_encontrados,
            "top_bairros_perdidos": top_bairros_perdidos,
            "latest_cases": latest_cases,
            "stats_chart": stats_chart,
            "sem_dados": sem_dados if not (total_perdidos > 0 or total_encontrados > 0 or comentarios_data) else False
        }
        return dashboard_data

    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao gerar dados do dashboard: {e}")
        return {"sem_dados": True} # Retorna um dict indicando erro/sem dados
    finally:
        if conn:
            conn.close()

@app.route('/dashboard')
def dashboard():
    data = gerar_dados_dashboard_pets()
    if not data: # Se gerar_dados_dashboard_pets falhar na conexão
        flash("Erro ao carregar dados para o dashboard.", "danger")
        data = {"sem_dados": True} # Garante que 'data' é um dict

    return render_template('dashboard.html', data=data, current_year=datetime.now().year)


@app.route('/confirmar_encerrar_busca/<int:pet_id>')
def confirmar_encerrar_busca(pet_id):
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco.", "danger")
        return redirect(url_for('detalhes_pet', pet_id=pet_id)) # Redireciona para detalhes em caso de erro de conexão

    pet_file_paths = None
    try:
        with conn.cursor() as cursor_select:
            # Buscamos FOTO_PATH e THUMBNAIL_PATH para deletar do S3
            cursor_select.execute("SELECT FOTO_PATH, THUMBNAIL_PATH FROM USERINPUT WHERE ID = %s", (pet_id,))
            pet_file_paths = cursor_select.fetchone()
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar caminhos de arquivo para o pet ID {pet_id} antes de deletar: {e}")
        flash("Erro ao preparar para encerrar busca (não foi possível ler caminhos dos arquivos).", "danger")
        if conn: conn.close()
        return redirect(url_for('detalhes_pet', pet_id=pet_id))

    if not pet_file_paths:
        flash("Pet não encontrado para buscar caminhos de arquivo.", "warning")
        if conn: conn.close()
        return redirect(url_for('principal')) # Pet não existe, volta para principal

    try:
        with conn.cursor() as cursor_update:
            sql_update = "UPDATE USERINPUT SET RESOLVIDO = 1, RESOLVIDO_AT = %s WHERE ID = %s AND (RESOLVIDO = 0 OR RESOLVIDO IS NULL)"
            affected_rows = cursor_update.execute(sql_update, (datetime.now(), pet_id))
            conn.commit()

        if affected_rows > 0:
            flash("Busca encerrada com sucesso no banco de dados!", "success")
            
            app.logger.info(f"Tentando deletar arquivos S3 para o pet ID {pet_id}...")
            s3_foto_key = pet_file_paths.get('FOTO_PATH')
            s3_thumbnail_key = pet_file_paths.get('THUMBNAIL_PATH')

            foto_deleted = delete_from_s3(S3_BUCKET, s3_foto_key)
            thumb_deleted = delete_from_s3(S3_BUCKET, s3_thumbnail_key)

            if foto_deleted and thumb_deleted:
                app.logger.info(f"Arquivos S3 para o pet ID {pet_id} processados para deleção (sucesso ou não existiam).")
            else:
                # Mesmo que a deleção falhe, a busca no DB foi encerrada.
                # O warning é para alertar o administrador sobre possíveis arquivos órfãos.
                flash("Busca encerrada, mas houve um problema ao tentar deletar os arquivos de imagem do armazenamento na nuvem. Verifique os logs do servidor.", "warning")
        else:
            flash("Pet não encontrado para encerrar a busca ou a busca já estava encerrada.", "info") # Mensagem mais informativa
            
    except pymysql.MySQLError as e_db_update:
        app.logger.error(f"Erro de banco de dados ao encerrar busca para pet ID {pet_id}: {e_db_update}")
        flash("Erro ao atualizar o status do pet no banco de dados.", "danger")
        if conn: conn.rollback()
    except Exception as e_main_logic:
        app.logger.error(f"Erro inesperado na lógica de encerrar busca para pet ID {pet_id}: {e_main_logic}")
        flash("Ocorreu um erro inesperado ao processar sua solicitação.", "danger")
        if conn and conn.open: conn.rollback()
    finally:
        if conn:
            conn.close()
            
    # Sempre redireciona para a página de detalhes do pet após a tentativa de encerrar
    # assim o usuário vê o status atualizado (ou a mensagem de erro se a busca já estava encerrada)
    return redirect(url_for('principal'))


@app.route('/pet/<int:pet_id>/add_message', methods=['POST'])
def add_message(pet_id):
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados ao tentar postar mensagem.", "danger")
        return redirect(url_for('detalhes_pet', pet_id=pet_id))

    commenter_name = request.form.get('commenter_name', 'Anônimo') # Pega o nome ou default 'Anônimo'
    message_text = request.form.get('message_text')

    if not message_text or len(message_text.strip()) == 0:
        flash("A mensagem não pode estar vazia.", "warning")
        return redirect(url_for('detalhes_pet', pet_id=pet_id))
    
    if len(message_text) > 100: # Validação do tamanho (consistente com o DB)
        flash("A mensagem é muito longa (máximo de 200 caracteres).", "warning")
        return redirect(url_for('detalhes_pet', pet_id=pet_id))

    try:
        with conn.cursor() as cursor:
            # Verificar se o PetID existe antes de inserir a mensagem
            cursor.execute("SELECT ID FROM USERINPUT WHERE ID = %s", (pet_id,))
            if not cursor.fetchone():
                flash("PET não encontrado para adicionar mensagem.", "danger")
                return redirect(url_for('principal'))

            sql = "INSERT INTO MESSAGES (PetID, CommenterName, MessageText) VALUES (%s, %s, %s)"
            cursor.execute(sql, (pet_id, commenter_name.strip(), message_text.strip()))
            conn.commit()
            flash("Mensagem enviada com sucesso!", "success")
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao salvar mensagem para o pet ID {pet_id}: {e}")
        flash("Erro ao enviar mensagem.", "danger")
        conn.rollback() # Desfaz a transação em caso de erro
    finally:
        if conn:
            conn.close()
    
    return redirect(url_for('detalhes_pet', pet_id=pet_id))

if __name__ == '__main__':
    app.run(debug=True)