from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from markupsafe import Markup, escape # Importar escape e Markup
from dotenv import load_dotenv
import os
import secrets
import pymysql
from datetime import datetime
from PIL import Image # Para manipulação de imagens
import folium # Para o mapa
from werkzeug.utils import secure_filename # Para segurança no upload de arquivos

# Para o dashboard (se mantiver a lógica do exemplo)
import base64
from io import BytesIO
import matplotlib
matplotlib.use('Agg') # Define o backend como 'Agg' para não precisar de GUI
import matplotlib.pyplot as plt
import numpy as np

load_dotenv()
app = Flask(__name__)
app.secret_key = secrets.token_urlsafe(16)

# Configurações de Upload
UPLOAD_FOLDER_ORIGINAL = os.path.join('static', 'uploads', 'imagens_pet')
UPLOAD_FOLDER_THUMBNAIL = os.path.join('static', 'uploads', 'thumbnails_pet')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
THUMBNAIL_SIZE = (100, 100) # Tamanho do thumbnail

app.config['UPLOAD_FOLDER_ORIGINAL'] = UPLOAD_FOLDER_ORIGINAL
app.config['UPLOAD_FOLDER_THUMBNAIL'] = UPLOAD_FOLDER_THUMBNAIL

# Cria as pastas de upload se não existirem
os.makedirs(UPLOAD_FOLDER_ORIGINAL, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_THUMBNAIL, exist_ok=True)


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
        img = Image.open(image_path)
        img.thumbnail(size)
        img.save(thumbnail_path)
        return True
    except Exception as e:
        app.logger.error(f"Erro ao criar thumbnail para {image_path}: {e}")
        return False

def delete_pet_files(foto_path, thumbnail_path, app_logger):
    """Tenta deletar os arquivos de foto e thumbnail do pet."""
    files_deleted = True
    try:
        if foto_path and isinstance(foto_path, str):
            full_foto_path = os.path.join(app.static_folder, foto_path)
            if os.path.exists(full_foto_path):
                os.remove(full_foto_path)
                app_logger.info(f"Arquivo de foto deletado: {full_foto_path}")
            else:
                app_logger.warning(f"Arquivo de foto não encontrado para deleção: {full_foto_path}")
        else:
            app_logger.warning(f"Caminho da foto inválido ou ausente para deleção: {foto_path}")

        if thumbnail_path and isinstance(thumbnail_path, str):
            full_thumbnail_path = os.path.join(app.static_folder, thumbnail_path)
            if os.path.exists(full_thumbnail_path):
                os.remove(full_thumbnail_path)
                app_logger.info(f"Arquivo de thumbnail deletado: {full_thumbnail_path}")
            else:
                app_logger.warning(f"Arquivo de thumbnail não encontrado para deleção: {full_thumbnail_path}")
        else:
             app_logger.warning(f"Caminho do thumbnail inválido ou ausente para deleção: {thumbnail_path}")

    except OSError as e: # Captura erros de I/O como permissão negada, arquivo em uso, etc.
        app_logger.error(f"Erro de OS ao deletar arquivos do pet: {e}")
        files_deleted = False
    except Exception as e:
        app_logger.error(f"Erro inesperado ao deletar arquivos do pet: {e}")
        files_deleted = False
    return files_deleted

@app.route('/')
def principal():
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados.", "danger")
        return render_template('index.html', current_year=datetime.now().year, mapa_html=None)

    mapa_folium = None
    try:
        with conn.cursor() as cursor:
            # Garantir que THUMBNAIL_PATH está sendo selecionado
            sql = """
                SELECT ID, NOME_PET, ESPECIE, BAIRRO, STATUS_PET, THUMBNAIL_PATH, LATITUDE, LONGITUDE
                FROM USERINPUT 
                WHERE RESOLVIDO = 0 OR RESOLVIDO IS NULL 
                ORDER BY CREATED_AT DESC
            """
            cursor.execute(sql)
            pets_no_mapa = cursor.fetchall()

        if pets_no_mapa:
            avg_lat = sum(p['LATITUDE'] for p in pets_no_mapa if p['LATITUDE']) / len([p for p in pets_no_mapa if p['LATITUDE']]) if any(p['LATITUDE'] for p in pets_no_mapa) else -22.7532
            avg_lon = sum(p['LONGITUDE'] for p in pets_no_mapa if p['LONGITUDE']) / len([p for p in pets_no_mapa if p['LONGITUDE']]) if any(p['LONGITUDE'] for p in pets_no_mapa) else -47.3330
            
            mapa_folium = folium.Map(location=[avg_lat, avg_lon], zoom_start=13, tiles="CartoDB positron") # Tile mais limpo

            for pet in pets_no_mapa:
                if pet.get('LATITUDE') and pet.get('LONGITUDE') and pet.get('THUMBNAIL_PATH'):
                    
                    # URL para a página de detalhes do PET
                    detalhes_pet_url = url_for('detalhes_pet', pet_id=pet['ID'], _external=True)
                    # --- LÓGICA PARA O ÍCONE COLORIDO DO MARCADOR ---
                    status_pet_mapa = pet.get('STATUS_PET', 'Perdi meu PET') # Default para consistência
                    
                    # Caminho do thumbnail para usar no ícone do mapa
                    thumbnail_url_para_icone = '#'
                    if pet.get('THUMBNAIL_PATH') and isinstance(pet['THUMBNAIL_PATH'], str):
                        thumbnail_url_para_icone = url_for('static', filename=pet['THUMBNAIL_PATH'])

                    icon_border_color = "red" # Default para 'Perdi meu PET'
                    if status_pet_mapa == "Encontrei um PET":
                        icon_border_color = "green"
                    
                    # HTML para o DivIcon (ícone customizado com borda colorida)
                    icon_html = f"""
                    <div style="
                        width: 52px; /* Tamanho total do ícone (imagem + borda) */
                        height: 52px;
                        border-radius: 50%; /* Círculo */
                        background-color: {icon_border_color}; /* Cor da borda/fundo */
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        box-shadow: 0px 0px 5px rgba(0,0,0,0.5);
                        padding: 2px; /* Espaçamento para a borda */
                        ">
                        <img src="{thumbnail_url_para_icone}" 
                            alt="T" 
                            style="
                                width: 48px; /* Tamanho da imagem interna */
                                height: 48px; 
                                border-radius: 50%; 
                                object-fit: cover;
                            ">
                    </div>
                    """
                    custom_map_icon = folium.DivIcon(
                        icon_size=(52, 52), # Tamanho do container do DivIcon
                        icon_anchor=(26, 52), # Ponto de ancoragem (metade da largura, base)
                        html=icon_html
                    )
                    # --- FIM DA LÓGICA DO ÍCONE COLORIDO ---

                    # HTML para o POPUP do marcador (que agora é um link para a página de detalhes)
                    # Vamos simplificar o popup para ser apenas um link claro
                    popup_html_content = f"""
                    <div style="font-family: 'Nunito', sans-serif; text-align:center; min-width:180px; padding: 10px;">
                        <strong style="font-size: 1.1em; color: #2D3748;">{pet.get('NOME_PET', 'Pet')}</strong><br>
                        <span style="font-size: 0.9em; color: #6A7588;">({pet.get('ESPECIE', '')})</span><br>
                        <a href="{detalhes_pet_url}" target="_blank" 
                           class="popup-details-link"> 
                           Ver Detalhes do PET
                        </a>
                    </div>
                    """

                    # Estilos para o popup (para garantir que o link seja bem visível e clicável)
                    popup_styles = """
                    <style>
                        body { margin:0; font-family: 'Nunito', sans-serif; }
                        .popup-details-link {
                            display: inline-block;
                            margin-top: 8px;
                            padding: 6px 12px;
                            background-color: #4A90E2; /* Cor primária do tema */
                            color: white !important; /* Cor do texto branca */
                            text-decoration: none;
                            border-radius: 20px; /* Bordas arredondadas como os botões */
                            font-weight: 600;
                            font-size: 0.9em;
                            transition: background-color 0.2s ease;
                        }
                        .popup-details-link:hover {
                            background-color: #357ABD; /* Tom mais escuro no hover */
                        }
                    </style>
                    """

                    full_popup_html = popup_styles + popup_html_content
                    
                    iframe = folium.IFrame(full_popup_html, width=220, height=110) # Iframe ajustado
                    popup = folium.Popup(iframe, max_width=220)

                    # # Ícone do marcador no mapa (thumbnail)
                    # # Garantir que THUMBNAIL_PATH use barras normais ao construir o caminho do sistema
                    # thumbnail_rel_path = pet['THUMBNAIL_PATH'].replace('/', os.sep) if pet['THUMBNAIL_PATH'] else None
                    # thumbnail_filesystem_path = os.path.join(app.static_folder, thumbnail_rel_path) if thumbnail_rel_path else None

                    # if thumbnail_filesystem_path and os.path.exists(thumbnail_filesystem_path):
                    #     custom_icon = folium.CustomIcon(thumbnail_filesystem_path, icon_size=(50,50)) # Ícone um pouco maior
                    # else:
                    #     app.logger.warning(f"Thumbnail não encontrado ou caminho inválido: {thumbnail_filesystem_path if thumbnail_filesystem_path else 'N/A'}. Usando ícone padrão.")
                    #     custom_icon = folium.Icon(color='orange', icon='paw', prefix='fa') # Cor alterada para destaque
                    
                    marker = folium.Marker(
                        location=[pet['LATITUDE'], pet['LONGITUDE']],
                        icon=custom_map_icon,
                        # Tooltip ao passar o mouse
                        tooltip=f"<strong>{pet.get('NOME_PET', 'Pet')}</strong><br>Status: {status_pet_mapa}<br>Clique para mais informações"
                    )
                    marker.add_child(popup) # O popup agora contém o link "Ver Detalhes"
                    marker.add_to(mapa_folium)

            mapa_html = mapa_folium._repr_html_() if mapa_folium else "<p class='text-center alert alert-info'>Nenhum pet perdido para exibir no mapa no momento.</p>"
        else:
            mapa_folium = folium.Map(location=[-22.7532, -47.3330], zoom_start=12, tiles="CartoDB positron")
            mapa_html = mapa_folium._repr_html_()
            flash("Nenhum pet cadastrado como perdido ou encontrado no momento.", "info")
            
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar pets para o mapa: {e}")
        flash("Erro ao carregar dados dos pets.", "danger")
        mapa_html = "<p class='text-center alert alert-danger'>Erro ao carregar o mapa. Tente novamente mais tarde.</p>"
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
    latest_messages = [] # Lista para as mensagens
    try:
        with conn.cursor() as cursor:
            # Query precisa buscar todos os campos necessários para a página de detalhes
            sql = """
                SELECT ID, NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                       FOTO_PATH, CREATED_AT, STATUS_PET, RESOLVIDO
                FROM USERINPUT 
                WHERE ID = %s
            """
            cursor.execute(sql, (pet_id,))
            pet_info = cursor.fetchone()
            if pet_info: # Buscar mensagens apenas se o pet for encontrado
                sql_messages = """
                    SELECT CommenterName, MessageText, CreatedAt
                    FROM MESSAGES
                    WHERE PetID = %s
                    ORDER BY CreatedAt DESC
                    LIMIT 3 
                """ # Busca as 3 últimas mensagens
                cursor.execute(sql_messages, (pet_id,))
                latest_messages = cursor.fetchall()

    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar detalhes do pet ID {pet_id}: {e}")
        flash("Erro ao carregar informações do pet.", "danger")
        return redirect(url_for('principal'))
    finally:
        if conn:
            conn.close()

    if not pet_info:
        flash("Pet não encontrado.", "warning")
        return redirect(url_for('principal'))

    foto_url = '#'
    if pet_info.get('FOTO_PATH') and isinstance(pet_info['FOTO_PATH'], str):
        # FOTO_PATH já deve estar como 'uploads/imagens_pet/arquivo.png'
        foto_url = url_for('static', filename=pet_info['FOTO_PATH'])
        
    url_encerrar = url_for('confirmar_encerrar_busca', pet_id=pet_info['ID'])

# Definir classe CSS para o status
    status_pet_classe = "status-perdi-text" # Default
    if pet_info.get('STATUS_PET') == "Encontrei um PET":
        status_pet_classe = "status-encontrado-text"
    elif pet_info.get('RESOLVIDO'): # Se já resolvido, pode ter uma classe diferente ou a mesma de encontrado
        status_pet_classe = "status-resolvido-text" # Exemplo para uma cor diferente se resolvido


    return render_template('detalhes_pet.html', 
                           pet=pet_info, 
                           foto_url=foto_url,
                           url_encerrar=url_encerrar,
                           status_classe=status_pet_classe,
                           messages=latest_messages, # <<<< PASSANDO AS MENSAGENS PARA O TEMPLATE
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
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados. Não é possível carregar os bairros.", "danger")
        return render_template('cadastrar_pet.html', bairros=[])

    bairros = []
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT BAIRRO FROM LOCATIONS ORDER BY BAIRRO ASC;")
            bairros_data = cursor.fetchall()
            bairros = [row['BAIRRO'] for row in bairros_data]
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar bairros: {e}")
        flash("Erro ao carregar lista de bairros.", "danger")

    if request.method == 'POST':
        nome_pet = request.form.get('nome_pet')
        especie = request.form.get('especie')
        rua = request.form.get('rua')
        bairro = request.form.get('bairro')
        cidade = request.form.get('cidade', 'Americana/SP') # Default se não enviado
        contato = request.form.get('contato')
        comentario = request.form.get('comentario')
        status_pet = request.form.get('status_pet', 'Perdi meu PET') # <<<< NOVO CAMPO
        
        if 'foto_pet' not in request.files:
            flash('Nenhum arquivo de foto enviado!', 'danger')
            return redirect(request.url)
        
        file = request.files['foto_pet']
        if file.filename == '':
            flash('Nenhum arquivo selecionado!', 'danger')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}")
            original_filepath = os.path.join(app.config['UPLOAD_FOLDER_ORIGINAL'], filename)
            thumbnail_filename = f"thumb_{filename}"
            thumbnail_filepath = os.path.join(app.config['UPLOAD_FOLDER_THUMBNAIL'], thumbnail_filename)
            
            try:
                file.save(original_filepath)
                if not create_thumbnail(original_filepath, thumbnail_filepath):
                    flash('Erro ao criar thumbnail da imagem.', 'danger')
                    # Considerar remover o arquivo original se o thumbnail falhar
                    if os.path.exists(original_filepath):
                        os.remove(original_filepath)
                    return redirect(request.url)

                # Obter coordenadas da tabela LOCATIONS
                lat, lon = None, None
                if conn: # Reabrir conexão se fechou após buscar bairros
                    if not conn.open: conn = open_conn()
                
                if conn and bairro and rua: # Garantir que temos conexão e dados para buscar
                    try:
                        with conn.cursor() as cursor_coords:
                            sql_coords = "SELECT LATITUDE, LONGITUDE FROM LOCATIONS WHERE BAIRRO = %s AND RUA = %s LIMIT 1"
                            cursor_coords.execute(sql_coords, (bairro, rua))
                            coords_data = cursor_coords.fetchone()
                            if coords_data:
                                lat, lon = coords_data['LATITUDE'], coords_data['LONGITUDE']
                            else:
                                flash(f'Coordenadas não encontradas para {rua}, {bairro}. O pet será cadastrado sem geolocalização precisa no mapa.', 'warning')
                    except pymysql.MySQLError as e:
                        app.logger.error(f"Erro ao buscar coordenadas: {e}")
                        flash('Erro ao obter coordenadas. O pet será cadastrado sem geolocalização precisa.', 'warning')
                else:
                     flash('Não foi possível buscar coordenadas devido à falta de dados ou conexão.', 'warning')


                # Salvar no banco
                if conn:
                     if not conn.open: conn = open_conn()
                
                if conn:
                    try:
                        with conn.cursor() as cursor_insert:
                            sql_insert = """
                                INSERT INTO USERINPUT 
                                (NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                                 FOTO_PATH, THUMBNAIL_PATH, CREATED_AT, RESOLVIDO, LATITUDE, LONGITUDE,
                                 STATUS_PET) -- <<<< ADICIONADA NOVA COLUNA
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s, %s) -- <<<< ADICIONADO NOVO PLACEHOLDER
                            """
                            # ---- CORREÇÃO IMPORTANTE AQUI ----
                            # Caminhos relativos a partir de 'static' para URL_FOR, usando '/'
                            db_foto_path = os.path.join('uploads', 'imagens_pet', filename).replace(os.sep, '/')
                            db_thumbnail_path = os.path.join('uploads', 'thumbnails_pet', thumbnail_filename).replace(os.sep, '/')
                            # ---- FIM DA CORREÇÃO ----

                            cursor_insert.execute(sql_insert, 
                                                (nome_pet, especie, rua, bairro, cidade, contato, comentario,
                                                db_foto_path, db_thumbnail_path, datetime.now(), lat, lon,
                                                status_pet)) # <<<< ADICIONADO NOVO VALOR
                            conn.commit()
                            flash('Pet cadastrado com sucesso!', 'success')
                            return redirect(url_for('principal'))
                    except pymysql.MySQLError as e:
                        app.logger.error(f"Erro ao inserir pet no banco: {e}")
                        flash(f'Erro ao salvar dados no banco: {e}', 'danger')
                        # Limpar arquivos se o DB falhar
                        if os.path.exists(original_filepath): os.remove(original_filepath)
                        if os.path.exists(thumbnail_filepath): os.remove(thumbnail_filepath)
                else:
                    flash('Erro de conexão com o banco ao tentar salvar o pet.', 'danger')
                    if os.path.exists(original_filepath): os.remove(original_filepath)
                    if os.path.exists(thumbnail_filepath): os.remove(thumbnail_filepath)


            except Exception as e_file:
                app.logger.error(f"Erro no processamento do arquivo: {e_file}")
                flash(f'Erro ao processar arquivo: {e_file}', 'danger')
                return redirect(request.url)
        else:
            flash('Tipo de arquivo não permitido!', 'danger')
            return redirect(request.url)
    
    # Fechar a conexão principal se ainda estiver aberta e não for usada no POST
    if conn and request.method == 'GET':
        conn.close()
        
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

    wordcloud_image, latest_cases, stats_chart, sem_dados = None, None, None, True
    
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
            
            fig, ax = plt.subplots(figsize=(5,3)) # Ajustar tamanho
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
            "wordcloud_image": wordcloud_image,
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
        return redirect(url_for('principal'))

    # Primeiro, buscar os caminhos dos arquivos ANTES de marcar como resolvido
    pet_file_paths = None
    try:
        with conn.cursor() as cursor_select:
            cursor_select.execute("SELECT FOTO_PATH, THUMBNAIL_PATH FROM USERINPUT WHERE ID = %s", (pet_id,))
            pet_file_paths = cursor_select.fetchone()
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar caminhos de arquivo para o pet ID {pet_id} antes de deletar: {e}")
        flash("Erro ao preparar para encerrar busca (não foi possível ler caminhos dos arquivos).", "danger")
        if conn: conn.close()
        return redirect(url_for('principal'))

    if not pet_file_paths:
        flash("Pet não encontrado para buscar caminhos de arquivo.", "warning")
        if conn: conn.close()
        return redirect(url_for('principal'))

    # Agora, tentar marcar como resolvido
    try:
        with conn.cursor() as cursor_update:
            sql = "UPDATE USERINPUT SET RESOLVIDO = 1, RESOLVIDO_AT = %s WHERE ID = %s AND (RESOLVIDO = 0 OR RESOLVIDO IS NULL)"
            affected_rows = cursor_update.execute(sql, (datetime.now(), pet_id))
            conn.commit()

        if affected_rows > 0:
            flash("Busca encerrada com sucesso no banco de dados!", "success")
            
            # Tentar deletar os arquivos após o commit bem-sucedido
            app.logger.info(f"Tentando deletar arquivos para o pet ID {pet_id}...")
            foto_path_db = pet_file_paths.get('FOTO_PATH')
            thumbnail_path_db = pet_file_paths.get('THUMBNAIL_PATH')

            # Os caminhos no DB devem ser relativos a 'static/', ex: 'uploads/imagens_pet/...'
            # A função delete_pet_files já usa app.static_folder para construir o caminho absoluto.
            if delete_pet_files(foto_path_db, thumbnail_path_db, app.logger):
                app.logger.info(f"Arquivos para o pet ID {pet_id} processados para deleção.")
                # Não precisamos de um flash específico para a deleção bem-sucedida de arquivos,
                # a menos que seja muito importante para o usuário saber.
            else:
                flash("Busca encerrada, mas houve um problema ao deletar os arquivos de imagem do servidor. Contate o administrador.", "warning")
        
        else:
            flash("Pet não encontrado ou busca já encerrada no banco.", "warning")
            
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro de banco de dados ao encerrar busca para pet ID {pet_id}: {e}")
        flash("Erro ao atualizar o status do pet no banco de dados.", "danger")
        if conn: conn.rollback() # Desfaz a transação em caso de erro no UPDATE
    except Exception as e_main: # Captura outros erros inesperados na lógica principal
        app.logger.error(f"Erro inesperado na lógica de encerrar busca para pet ID {pet_id}: {e_main}")
        flash("Ocorreu um erro inesperado ao processar sua solicitação.", "danger")
        if conn and conn.open: conn.rollback()
    finally:
        if conn:
            conn.close()
            
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