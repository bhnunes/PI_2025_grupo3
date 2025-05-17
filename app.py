from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
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

@app.route('/')
def principal():
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco de dados.", "danger")
        return render_template('index.html', current_year=datetime.now().year, mapa_html=None) # Removido pets=[]

    mapa_folium = None
    # pets_no_mapa = [] # Não precisa inicializar aqui se a query sempre retorna algo ou None
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT ID, NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                       THUMBNAIL_PATH, LATITUDE, LONGITUDE, CREATED_AT, FOTO_PATH,
                       STATUS_PET
                FROM USERINPUT 
                WHERE RESOLVIDO = 0 OR RESOLVIDO IS NULL 
                ORDER BY CREATED_AT DESC
            """
            cursor.execute(sql)
            pets_no_mapa = cursor.fetchall()

        if pets_no_mapa:
            avg_lat = sum(p['LATITUDE'] for p in pets_no_mapa if p['LATITUDE']) / len([p for p in pets_no_mapa if p['LATITUDE']]) if any(p['LATITUDE'] for p in pets_no_mapa) else -22.7532
            avg_lon = sum(p['LONGITUDE'] for p in pets_no_mapa if p['LONGITUDE']) / len([p for p in pets_no_mapa if p['LONGITUDE']]) if any(p['LONGITUDE'] for p in pets_no_mapa) else -47.3330
            
            mapa_folium = folium.Map(location=[avg_lat, avg_lon], zoom_start=13)

            for pet in pets_no_mapa:
                if pet['LATITUDE'] and pet['LONGITUDE'] and pet['THUMBNAIL_PATH']:
                    
                    encerrar_url = url_for('confirmar_encerrar_busca', pet_id=pet['ID'], _external=False) # _external=False é geralmente melhor para URLs internas
                    status_texto = pet.get('STATUS_PET', 'Status não informado')
                    local_completo = f"{pet['RUA']}, {pet['BAIRRO']}, {pet['CIDADE']}"

                    # CORREÇÃO DA URL DA IMAGEM:
                    # Assumindo que pet['FOTO_PATH'] é 'uploads/imagens_pet/nome_da_foto.png'
                    # url_for já sabe que 'static' é o diretório base para 'filename'
                    foto_pet_url = url_for('static', filename=pet['FOTO_PATH']) if pet['FOTO_PATH'] else '#'
                    print(foto_pet_url)
                    # O .replace('static/', '', 1) não é necessário se FOTO_PATH já é relativo à pasta static.
                    # E se FOTO_PATH começar com '\' (Windows) o url_for pode não gostar,
                    # então garantir que seja salvo com '/' no banco é melhor.

                    # ESTILOS CSS PARA O POPUP (INLINE OU BLOCO <STYLE>)
                    # Moveremos os estilos do styles.css para cá
                    # popup_styles = """
                    # <style>
                    #     body { font-family: 'Nunito', sans-serif; margin: 0; padding: 0; } /* Reset básico para o corpo do iframe */
                    #     .pet-popup-container {
                    #         padding: 15px; /* Reduzido um pouco para caber melhor */
                    #         color: #4A5568;
                    #         line-height: 1.5; /* Ajustado */
                    #         max-width: 260px; /* Para garantir que caiba no iframe default */
                    #         word-wrap: break-word; /* Quebra palavras longas */
                    #     }
                    #     .pet-popup-name {
                    #         font-family: 'Pacifico', cursive !important;
                    #         color: #DD6B20 !important;
                    #         font-size: 1.5em !important; /* Ajustado */
                    #         margin-bottom: 3px !important;
                    #         text-align: center;
                    #         line-height: 1.1;
                    #     }
                    #     .pet-popup-species {
                    #         font-family: 'Nunito', sans-serif !important;
                    #         font-size: 0.75em; /* Ajustado */
                    #         color: #718096;
                    #         font-weight: 600;
                    #         display: block;
                    #         text-align: center;
                    #         margin-top: -4px;
                    #     }
                    #     .pet-popup-status {
                    #         font-weight: 700;
                    #         color: #4A90E2;
                    #         margin-top: 8px; /* Adicionado espaço acima */
                    #         margin-bottom: 10px; /* Reduzido */
                    #         font-size: 1.0em; /* Ajustado */
                    #         text-align: center;
                    #         padding: 4px 0px; /* Padding ajustado */
                    #         background-color: rgba(74, 144, 226, 0.08); /* Mais sutil */
                    #         border-radius: 4px;
                    #     }
                    #     .pet-popup-image {
                    #         display: block;
                    #         width: 100%;
                    #         max-width: 180px; /* Reduzido para caber melhor */
                    #         height: auto;
                    #         border-radius: 6px;
                    #         margin: 0 auto 12px auto;
                    #         border: 1px solid #dde; /* Borda mais sutil */
                    #         box-shadow: 0 1px 4px rgba(0,0,0,0.1);
                    #     }
                    #     .pet-popup-details p {
                    #         margin-bottom: 6px;
                    #         font-size: 0.9em; /* Reduzido para caber mais info */
                    #     }
                    #     .pet-popup-details .detail-label {
                    #         color: #2D3748;
                    #         font-weight: 700;
                    #         margin-right: 4px;
                    #     }
                    #     .pet-popup-details .pet-info-text {
                    #         color: #5A6779;
                    #         display: inline; /* Para permitir quebra, mas fluir com o label se curto */
                    #     }
                    #     .pet-popup-button {
                    #         display: block;
                    #         width: 100%;
                    #         margin-top: 12px !important;
                    #         background-color: #38A169 !important;
                    #         border: none !important; /* Removida borda para consistência com .btn */
                    #         color: white !important;
                    #         padding: 7px 10px !important;
                    #         font-size: 0.9em !important;
                    #         font-weight: 600 !important;
                    #         border-radius: 20px !important;
                    #         text-align: center;
                    #         text-transform: none !important;
                    #         letter-spacing: normal !important;
                    #         transition: background-color 0.2s ease;
                    #         text-decoration: none !important;
                    #         box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                    #     }
                    #     .pet-popup-button:hover {
                    #         background-color: #2F855A !important;
                    #         text-decoration: none !important;
                    #     }
                    # </style>
                    # """

                    popup_html_content = f"""
                    <div class="pet-popup-container">
                        <h4 class="pet-popup-name">{pet.get('NOME_PET', 'Pet Desconhecido')} 
                            <span class="pet-popup-species">({pet['ESPECIE']})</span>
                        </h4>
                        <p class="pet-popup-status">{status_texto}</p>
                        
                        <img src='{foto_pet_url}' alt="Foto do PET: {pet.get('NOME_PET', '')}" class="pet-popup-image">
                        
                        <div class="pet-popup-details">
                            <p><strong class="detail-label">Visto por último em:</strong> {local_completo}</p>
                            <p><strong class="detail-label">Contato:</strong> {pet['CONTATO']}</p>
                            <p><strong class="detail-label">Informações:</strong> 
                               <span class="pet-info-text">{pet['COMENTARIO'][:150] + '...' if pet['COMENTARIO'] and len(pet['COMENTARIO']) > 150 else pet['COMENTARIO'] or 'Nenhuma informação adicional.'}</span>
                            </p>
                            <p><strong class="detail-label">Cadastrado em:</strong> {pet['CREATED_AT'].strftime('%d/%m/%Y %H:%M')}</p>
                        </div>
                        
                        <a href="{encerrar_url}" 
                           class="pet-popup-button"
                           onclick="return confirm('Tem certeza que deseja encerrar a busca por este PET? Esta ação não pode ser desfeita.');"
                           target="_top"> 
                           Encerrar Busca
                        </a>
                    </div>
                    """
                    
                    # Combinar estilos e conteúdo HTML
                    #full_popup_html = popup_styles + popup_html_content

                    #iframe = folium.IFrame(full_popup_html, width=400, height=520) # Ajustado para mais conteúdo
                    iframe = folium.IFrame(popup_html_content, width=300, height=420) # Use o HTML sem os estilos customizados
                    popup = folium.Popup(iframe, max_width=300)

                    thumbnail_filesystem_path = os.path.join(app.static_folder, pet['THUMBNAIL_PATH'])
                    if os.path.exists(thumbnail_filesystem_path):
                        custom_icon = folium.CustomIcon(thumbnail_filesystem_path, icon_size=(40,40))
                    else:
                        app.logger.warning(f"Arquivo de thumbnail não encontrado em: {thumbnail_filesystem_path}. Usando ícone padrão.")
                        custom_icon = folium.Icon(color='blue', icon='paw', prefix='fa')

                    folium.Marker(
                        [pet['LATITUDE'], pet['LONGITUDE']],
                        popup=popup,
                        tooltip=f"{pet.get('NOME_PET', 'Pet')} - {pet['BAIRRO']}",
                        icon=custom_icon
                    ).add_to(mapa_folium)
            mapa_html = mapa_folium._repr_html_() if mapa_folium else "<p>Nenhum pet perdido para exibir no mapa.</p>"
        else:
            mapa_folium = folium.Map(location=[-22.7532, -47.3330], zoom_start=12)
            mapa_html = mapa_folium._repr_html_()
            
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao buscar pets para o mapa: {e}")
        flash("Erro ao carregar dados dos pets.", "danger")
        mapa_html = "<p>Erro ao carregar o mapa. Tente novamente mais tarde.</p>"
    finally:
        if conn:
            conn.close()
            
    return render_template('index.html', 
                           current_year=datetime.now().year, 
                           mapa_html=mapa_html)

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


# Em app.py
@app.route('/confirmar_encerrar_busca/<int:pet_id>')
def confirmar_encerrar_busca(pet_id):
    # Você pode adicionar uma página de confirmação aqui se desejar
    # Ou processar diretamente e redirecionar
    conn = open_conn()
    if not conn:
        flash("Erro de conexão com o banco.", "danger")
        return redirect(url_for('principal'))
    try:
        with conn.cursor() as cursor:
            sql = "UPDATE USERINPUT SET RESOLVIDO = 1, RESOLVIDO_AT = %s WHERE ID = %s AND (RESOLVIDO = 0 OR RESOLVIDO IS NULL)"
            affected_rows = cursor.execute(sql, (datetime.now(), pet_id))
            conn.commit()
        if affected_rows > 0:
            flash("Busca encerrada com sucesso!", "success")
        else:
            flash("Pet não encontrado ou busca já encerrada.", "warning")
    except pymysql.MySQLError as e:
        app.logger.error(f"Erro ao encerrar busca para pet ID {pet_id}: {e}")
        flash("Erro ao atualizar o banco de dados.", "danger")
    finally:
        if conn:
            conn.close()
    return redirect(url_for('principal'))

if __name__ == '__main__':
    app.run(debug=True)