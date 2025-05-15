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
import random
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
        return render_template('index.html', current_year=datetime.now().year, mapa_html=None, pets=[])

    mapa_folium = None
    pets_no_mapa = []
    try:
        with conn.cursor() as cursor:
            # Buscar pets não resolvidos
            sql = """
                SELECT ID, NOME_PET, ESPECIE, RUA, BAIRRO, CIDADE, CONTATO, COMENTARIO, 
                       THUMBNAIL_PATH, LATITUDE, LONGITUDE, CREATED_AT, FOTO_PATH
                FROM USERINPUT 
                WHERE RESOLVIDO = 0 OR RESOLVIDO IS NULL 
                ORDER BY CREATED_AT DESC
            """
            cursor.execute(sql)
            pets_no_mapa = cursor.fetchall()

        if pets_no_mapa:
            # Centralizar mapa na média das coordenadas ou em uma localização padrão
            avg_lat = sum(p['LATITUDE'] for p in pets_no_mapa if p['LATITUDE']) / len([p for p in pets_no_mapa if p['LATITUDE']]) if any(p['LATITUDE'] for p in pets_no_mapa) else -22.7532  # Americana-SP aprox.
            avg_lon = sum(p['LONGITUDE'] for p in pets_no_mapa if p['LONGITUDE']) / len([p for p in pets_no_mapa if p['LONGITUDE']]) if any(p['LONGITUDE'] for p in pets_no_mapa) else -47.3330 # Americana-SP aprox.
            
            mapa_folium = folium.Map(location=[avg_lat, avg_lon], zoom_start=13)

            for pet in pets_no_mapa:
                if pet['LATITUDE'] and pet['LONGITUDE'] and pet['THUMBNAIL_PATH']:

                    encerrar_url = url_for('confirmar_encerrar_busca', pet_id=pet['ID'], _external=True) # _external pode ajudar com iframes
                    popup_html = f"""
                        <h4>{pet.get('NOME_PET', 'Sem nome')} ({pet['ESPECIE']})</h4>
                        <img src='{url_for('static', filename=pet['FOTO_PATH'].replace('static/', '', 1))}' width='150'><br>
                        <b>Local:</b> {pet['RUA']}, {pet['BAIRRO']}, {pet['CIDADE']}<br>
                        <b>Contato:</b> {pet['CONTATO']}<br>
                        <b>Info:</b> {pet['COMENTARIO'][:100] + '...' if pet['COMENTARIO'] and len(pet['COMENTARIO']) > 100 else pet['COMENTARIO']}<br>
                        <b>Cadastrado em:</b> {pet['CREATED_AT'].strftime('%d/%m/%Y %H:%M')}<br>
                        <a href="{encerrar_url}" 
                        class="btn btn-sm btn-success" 
                        onclick="return confirm('Tem certeza que deseja encerrar a busca por este PET? Esta ação não pode ser desfeita.');"
                        target="_top"> 
                        Encerrar Busca
                        </a>
                    """
                    iframe = folium.IFrame(popup_html, width=250, height=300)
                    popup = folium.Popup(iframe, max_width=2650)

                    thumbnail_filesystem_path = os.path.join(app.static_folder, pet['THUMBNAIL_PATH'])
                    if os.path.exists(thumbnail_filesystem_path):
                        custom_icon = folium.CustomIcon(thumbnail_filesystem_path, icon_size=(40,40))
                    else:
                        app.logger.warning(f"Arquivo de thumbnail não encontrado em: {thumbnail_filesystem_path}. Usando ícone padrão.")
                        # Fallback para um ícone padrão do Folium se o thumbnail não for encontrado
                        custom_icon = folium.Icon(color='blue', icon='paw', prefix='fa') # Exemplo

                    folium.Marker(
                        [pet['LATITUDE'], pet['LONGITUDE']],
                        popup=popup,
                        tooltip=f"{pet.get('NOME_PET', 'Pet')} - {pet['BAIRRO']}",
                        icon=custom_icon # ou folium.Icon(color='blue', icon='paw', prefix='fa') se tiver FontAwesome
                    ).add_to(mapa_folium)
            mapa_html = mapa_folium._repr_html_() if mapa_folium else "<p>Nenhum pet perdido para exibir no mapa.</p>"
        else:
            # Mapa padrão se não houver pets
            mapa_folium = folium.Map(location=[-22.7532, -47.3330], zoom_start=12) # Americana-SP aprox.
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
                                 FOTO_PATH, THUMBNAIL_PATH, CREATED_AT, RESOLVIDO, LATITUDE, LONGITUDE)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
                            """
                            # Caminhos relativos a partir de 'static' para URL_FOR
                            db_foto_path = os.path.join('uploads', 'imagens_pet', filename)
                            db_thumbnail_path = os.path.join('uploads', 'thumbnails_pet', thumbnail_filename)

                            cursor_insert.execute(sql_insert, 
                                                (nome_pet, especie, rua, bairro, cidade, contato, comentario,
                                                db_foto_path, db_thumbnail_path, datetime.now(), lat, lon))
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

        if comentarios_data:
            sem_dados = False
            text = " ".join([item['COMENTARIO'] for item in comentarios_data])
            if text.strip(): # Verifica se o texto não está vazio
                wordcloud = WordCloud(background_color="white", width=400, height=250, collocations=False).generate(text)
                image_bytes = BytesIO()
                wordcloud.to_image().save(image_bytes, format='PNG')
                image_bytes.seek(0)
                wordcloud_image = base64.b64encode(image_bytes.getvalue()).decode()
            else:
                wordcloud_image = None # Ou uma imagem placeholder
        
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