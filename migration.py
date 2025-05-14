import pymysql
import pandas as pd
from dotenv import load_dotenv
import os
from tqdm import tqdm
# import time # time não está sendo usado, pode ser removido se não for para debug

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Configurações do Banco de Dados (lidas do .env)
DB_HOST = os.getenv('MYSQL_HOST')
DB_USER = os.getenv('MYSQL_USER')
DB_PASSWORD = os.getenv('MYSQL_PASSWORD')
DB_NAME = os.getenv('MYSQL_DB')
DB_PORT = int(os.getenv('MYSQL_PORT', 3306)) # Default para MySQL padrão

# Caminho para o seu arquivo CSV
# ATUALIZE ESTE CAMINHO se necessário
csv_file_path = r"D:\Usuario\Desktop\PI_2025_1_semestre\PI_2025_grupo3\output.csv" 

# Nome da tabela no banco de dados
table_name = 'LOCATIONS'

# Define o tamanho do lote para commits
COMMIT_BATCH_SIZE = 300

def create_db_connection():
    """Cria e retorna uma conexão com o banco de dados."""
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except pymysql.MySQLError as e:
        print(f"Erro ao conectar ao MySQL: {e}")
        return None

def insert_data_from_csv(connection, csv_path):
    """Lê dados de um CSV e insere na tabela LOCATIONS, com commits em lotes."""
    failed_ceps = []
    successful_inserts_total = 0
    successful_inserts_in_batch = 0 # Contador para o lote atual

    try:
        try:
            df = pd.read_csv(csv_path, delimiter=';', encoding='utf-8', dtype=str)
        except UnicodeDecodeError:
            print("Falha ao decodificar como UTF-8. Tentando com 'latin1'...")
            df = pd.read_csv(csv_path, delimiter=';', encoding='latin1', dtype=str)

        df.columns = [col.strip().upper() for col in df.columns]

        expected_cols = ['RUA', 'BAIRRO', 'CIDADE', 'CEP', 'LATITUDE', 'LONGITUDE']
        if not all(col in df.columns for col in expected_cols):
            missing_cols = [col for col in expected_cols if col not in df.columns]
            print(f"Erro: Colunas ausentes no CSV: {missing_cols}")
            return [], 0

        cursor = connection.cursor()
        
        sql_insert_query = f"""
            INSERT INTO {table_name} (RUA, BAIRRO, CIDADE, CEP, LATITUDE, LONGITUDE)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        print(f"Iniciando a inserção de {len(df)} linhas do arquivo {csv_path}...")

        for index, row in tqdm(df.iterrows(), total=df.shape[0], desc="Inserindo dados"):
            try:
                rua = str(row['RUA']).strip() if pd.notna(row['RUA']) else None
                bairro = str(row['BAIRRO']).strip() if pd.notna(row['BAIRRO']) else None
                cidade = str(row['CIDADE']).strip() if pd.notna(row['CIDADE']) else None
                cep = str(row['CEP']).strip() if pd.notna(row['CEP']) else None
                
                latitude_str = str(row['LATITUDE']).strip().replace(',', '.') if pd.notna(row['LATITUDE']) else None
                longitude_str = str(row['LONGITUDE']).strip().replace(',', '.') if pd.notna(row['LONGITUDE']) else None

                latitude = float(latitude_str) if latitude_str else None
                longitude = float(longitude_str) if longitude_str else None
                
                if not all([rua, bairro, cidade, latitude is not None, longitude is not None]):
                    # Não printamos mais aqui para não poluir o tqdm, mas registramos a falha
                    failed_ceps.append(cep or f"Linha_{index+2}_sem_dados_obrigatorios")
                    continue

                data_tuple = (
                    rua,
                    bairro,
                    cidade,
                    cep,
                    latitude,
                    longitude
                )
                cursor.execute(sql_insert_query, data_tuple)
                successful_inserts_total += 1
                successful_inserts_in_batch += 1

                # Verifica se atingiu o tamanho do lote para commit
                if successful_inserts_in_batch >= COMMIT_BATCH_SIZE:
                    connection.commit()
                    # tqdm.write(f"Commit de lote de {successful_inserts_in_batch} linhas realizado.") # Opcional: printar o commit do lote
                    successful_inserts_in_batch = 0 # Reseta o contador do lote

            except ValueError as ve:
                tqdm.write(f"Erro de valor na linha {index+2} (CEP: {row.get('CEP', 'N/A')}): {ve}")
                failed_ceps.append(row.get('CEP', f"Linha_{index+2}_sem_CEP_VE"))
            except pymysql.MySQLError as e:
                tqdm.write(f"Erro de banco de dados na linha {index+2} (CEP: {row.get('CEP', 'N/A')}): {e}")
                failed_ceps.append(row.get('CEP', f"Linha_{index+2}_sem_CEP_DBE"))
                # Em caso de erro de DB, é bom considerar se devemos tentar fazer rollback do lote atual
                # ou se a transação já foi implicitamente desfeita. Por simplicidade, não adicionamos rollback aqui.
            except Exception as ex:
                tqdm.write(f"Erro inesperado na linha {index+2} (CEP: {row.get('CEP', 'N/A')}): {ex}")
                failed_ceps.append(row.get('CEP', f"Linha_{index+2}_sem_CEP_UE"))
        
        # Commit final para quaisquer inserções restantes no último lote (se houver)
        if successful_inserts_in_batch > 0:
            connection.commit()
            # tqdm.write(f"Commit final de {successful_inserts_in_batch} linhas realizado.") # Opcional
        
        # print("Commit realizado no banco de dados.") # Removido, pois agora é feito em lotes ou no final do lote

    except FileNotFoundError:
        print(f"Erro: Arquivo CSV não encontrado em '{csv_path}'")
    except pd.errors.EmptyDataError:
        print(f"Erro: Arquivo CSV '{csv_path}' está vazio.")
    except Exception as e:
        print(f"Erro geral ao processar o CSV: {e}")
        if connection:
            try:
                connection.rollback() # Tenta reverter se houver uma transação pendente
                print("Rollback realizado devido a erro geral.")
            except pymysql.MySQLError as rb_err:
                print(f"Erro ao tentar fazer rollback: {rb_err}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()

    return failed_ceps, successful_inserts_total

if __name__ == "__main__":
    conn = create_db_connection()
    if conn:
        # Opcional: TRUNCATE TABLE
        # try:
        #     with conn.cursor() as cursor:
        #         cursor.execute(f"TRUNCATE TABLE {table_name}")
        #     conn.commit()
        #     print(f"Tabela {table_name} limpa antes da importação.")
        # except pymysql.MySQLError as e:
        #     print(f"Erro ao limpar a tabela {table_name}: {e}")
        #     conn.rollback()

        failed_insertions_ceps, success_count = insert_data_from_csv(conn, csv_file_path)
        
        print("\n--- Resumo da Importação ---")
        print(f"Total de linhas inseridas com sucesso: {success_count}")
        
        if failed_insertions_ceps:
            print(f"Total de linhas que falharam na inserção ou foram ignoradas: {len(failed_insertions_ceps)}")
            print("CEPs (ou identificadores de linha) das que falharam/foram ignoradas:")
            # Imprime apenas os primeiros N erros para não poluir muito se houver muitos
            for i, cep_info in enumerate(failed_insertions_ceps):
                if i < 20: # Imprime os primeiros 20 erros
                    print(f"- {cep_info}")
                elif i == 20:
                    print(f"... e mais {len(failed_insertions_ceps) - 20} erros.")
                    break
        else:
            print("Todas as linhas elegíveis foram inseridas ou nenhuma falha registrada.")
        
        conn.close()
        print("Conexão com o banco de dados fechada.")