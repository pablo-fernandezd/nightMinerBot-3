import os
import json
import time
import sys
from multiprocessing import Process, set_start_method
import traceback
import logging

# --- Dependencias de Cardano ---
from pycardano import (
    Address, 
    Network, 
    PaymentSigningKey, 
    PaymentVerificationKey,
    StakeSigningKey,         
    StakeVerificationKey,    
    HDWallet 
)
# Importar Mnemonic desde su propia librería (Correcto para tu entorno)
from mnemonic.mnemonic import Mnemonic
# Importamos las funciones CIP-8
from pycardano.cip import cip8
# Importamos Keys para simular teclas
from selenium.webdriver.common.keys import Keys 
# --- Fin Dependencias Cardano ---

# --- Dependencias de Selenium ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger()
# =============================================================================

# =============================================================================
# SECCIÓN 1: GESTOR DE CARTERAS (Lógica actual y funcional)
# =============================================================================

CARTERAS_DIR = "pool_de_carteras"
NETWORK = Network.MAINNET
PAYMENT_DERIVATION_PATH = "m/1852'/1815'/0'/0/0"
STAKE_DERIVATION_PATH = "m/1852'/1815'/0'/2/0"


def generar_nueva_cartera():
    """
    Genera la Base Address y obtiene las claves de Pago y Staking.
    (Utiliza el slicing de xprivate_key para compatibilidad con tu pycardano)
    """
    log.info("Iniciando generación de nueva cartera (Base Address)...")
    try:
        # 1. Genera la frase semilla
        mnemo_lib = Mnemonic("english")
        seed_phrase = mnemo_lib.generate(strength=256)

        # 2. Convierte la frase en semilla BIP39 (64 bytes) -> HEX
        seed_bytes = mnemo_lib.to_seed(seed_phrase)
        seed_hex_string = seed_bytes.hex()
        root_key = HDWallet.from_seed(seed_hex_string)
        log.debug("Clave raíz HDWallet creada.")

        # --- 3. CLAVES DE PAGO (PARA CIP-8) ---
        payment_derived_key = root_key.derive_from_path(PAYMENT_DERIVATION_PATH)
        # ¡IMPORTANTE!: Tu corrección descubierta: usar .xprivate_key y el slicing [0:32]
        payment_private_key_seed_32 = payment_derived_key.xprivate_key[0:32]
        payment_signing_key = PaymentSigningKey(payment_private_key_seed_32)
        payment_verification_key = PaymentVerificationKey.from_signing_key(payment_signing_key)

        # --- 4. CLAVES DE STAKING (Para la dirección) ---
        stake_derived_key = root_key.derive_from_path(STAKE_DERIVATION_PATH)
        stake_private_key_seed_32 = stake_derived_key.xprivate_key[0:32]
        stake_verification_key = StakeVerificationKey.from_signing_key(StakeSigningKey(stake_private_key_seed_32))

        # --- 5. Clave pública de PAGO (64 chars) ---
        public_key_hex = payment_verification_key.payload.hex()
        log.debug(f"Clave pública (Payment Key Payload) generada: {public_key_hex[:10]}... (len: {len(public_key_hex)})")

        # --- 6. Dirección Base (pago + staking) ---
        address = Address(
            payment_part=payment_verification_key.hash(),
            staking_part=stake_verification_key.hash(),
            network=NETWORK
        )
        
        log.info(f"Cartera (Base Address) generada: {str(address)[:20]}...")

        return {
            "seed_phrase": seed_phrase, 
            "address": str(address),
            "public_key_hex": public_key_hex, # Clave PÚBLICA de Pago (para el campo "Public key")
            "payment_private_key_hex": payment_private_key_seed_32.hex(), # Clave PRIVADA de Pago (para la firma CIP-8)
            "stake_private_key_hex": stake_private_key_seed_32.hex() # Clave PRIVADA de Staking (guardada por seguridad)
        }
    except Exception as e:
        log.error(f"Error generando cartera: {e}")
        traceback.print_exc()
        return None

def guardar_cartera(wallet_data, filepath):
    """Guarda los datos de la cartera en un archivo JSON."""
    try:
        with open(filepath, 'w') as f:
            json.dump(wallet_data, f, indent=4)
        return True
    except IOError as e:
        log.error(f"Error guardando archivo {filepath}: {e}")
        return False

def gestionar_pool_de_carteras(cantidad_deseada):
    """Asegura que el número deseado de carteras exista."""
    log.info("Iniciando gestión de pool de carteras...")
    if not os.path.exists(CARTERAS_DIR):
        log.info(f"Creando directorio '{CARTERAS_DIR}'...")
        os.makedirs(CARTERAS_DIR)

    archivos_existentes = [f for f in os.listdir(CARTERAS_DIR) if f.startswith('wallet_') and f.endswith('.json')]
    cantidad_existente = len(archivos_existentes)
    
    carteras_a_crear = cantidad_deseada - cantidad_existente

    if carteras_a_crear <= 0:
        log.info(f"Ya existen {cantidad_existente} carteras. No se crearán nuevas.")
        return

    log.info(f"Se crearán {carteras_a_crear} carteras nuevas.")
    for i in range(carteras_a_crear):
        nuevo_id = cantidad_existente + i + 1
        filepath = os.path.join(CARTERAS_DIR, f"wallet_{nuevo_id}.json")
        
        log.info(f"Generando wallet_{nuevo_id}...")
        nueva_cartera = generar_nueva_cartera()
        
        if nueva_cartera and guardar_cartera(nueva_cartera, filepath):
            log.info(f"Éxito: Cartera {nuevo_id} guardada.")
        else:
            log.warning(f"Fallo: No se pudo crear o guardar la cartera {nuevo_id}.")
            
    log.info("Gestión de pool de carteras completada.\n")


# =============================================================================
# SECCIÓN 2: LÓGICA DEL BOT (WORKER) - (¡EDICIÓN MANUAL DE TECLAS!)
# =============================================================================

# --- ¡FUNCIÓN DE FIRMA CIP-8! ---
def firmar_mensaje_cip8(payment_signing_key: PaymentSigningKey, message_str: str) -> str:
    """
    Firma un mensaje usando el estándar CIP-8 con la Payment Signing Key.
    """
    try:
        signed_message_hex = cip8.sign(
            message=message_str,
            signing_key=payment_signing_key, # USAMOS LA CLAVE DE PAGO
            attach_cose_key=False # Usamos False porque pegaremos la Public Key por separado
        )
        return signed_message_hex
    except Exception as e:
        log.error(f"Error al firmar el mensaje CIP-8: {e}")
        return ""
# --- FIN DE FUNCIÓN AÑADIDA ---


def run_bot_worker(wallet_file_path):
    """
    Esta función es el TRABAJO que realizará CADA bot de Selenium.
    """
    
    # Extraer un ID simple para los logs, ej: "wallet_1"
    wallet_id = os.path.basename(wallet_file_path).split('.')[0]
    
    def log_bot(mensaje, level=logging.INFO):
        # Función helper para que todos los logs de este bot tengan su ID
        log.log(level, f"[{wallet_id}] {mensaje}")

    log_bot("Bot iniciado. Cargando datos de cartera...")

    # 1. Cargar datos de la cartera
    wallet_data = {} 
    try:
        with open(wallet_file_path, 'r') as f:
            wallet_data = json.load(f)
        
        address = wallet_data["address"]
        
        # --- LÓGICA DE CARGA CIP-8 ---
        public_key = wallet_data["public_key_hex"]
        private_key_hex = wallet_data["payment_private_key_hex"] 
        
        private_key_bytes = bytes.fromhex(private_key_hex)
        signing_key = PaymentSigningKey(private_key_bytes) 
        
        log_bot(f"Cartera cargada. Dirección: {address[:20]}...")
        
    except Exception as e:
        log_bot(f"ERROR: No se pudo cargar o parsear el archivo {wallet_file_path}: {e}", logging.ERROR)
        traceback.print_exc()
        return 

    # 2. Configurar Selenium
    chrome_options = Options()
    
    # --- Configuración de Chrome (Headless ON) ---
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36")
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20) 
        log_bot("Navegador iniciado.")
    except Exception as e:
        log_bot(f"ERROR: No se pudo iniciar Selenium. {e}", logging.ERROR)
        traceback.print_exc()
        return

    # 3. Bucle principal del bot (Lógica de clics)
    try:
        # Paso 1: Ir a la página
        driver.get("https://sm.midnight.gd/wizard/mine")
        log_bot(f"Abierta la página: {driver.title}")

        # Paso 2: Clic en "Enter an address manually"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(text(), 'Enter an address manually')]")
        )).click()
        log_bot("Clic en 'Enter an address manually'.")

        # Paso 3: Pegar la address
        wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@placeholder='Please enter an unused Cardano address']")
        )).send_keys(address)
        log_bot("Dirección (Base Address) pegada.")

        # Paso 4: Clic en "Continue"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Continue']")
        )).click()
        log_bot("Clic en 'Continue'.")

        # Paso 5: Clic en "Next"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Next']")
        )).click()
        log_bot("Clic en 'Next' (1/2).")

        # Paso 6: Clic en "Next" (otra vez)
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Next']")
        )).click()
        log_bot("Clic en 'Next' (2/2).")

        # Paso 7: Scroll y clic en checkbox "accept-terms"
        log_bot("Página de términos. Buscando checkbox...")
        checkbox = wait.until(EC.presence_of_element_located(
            (By.ID, "accept-terms")
        ))
        driver.execute_script("arguments[0].click();", checkbox)
        log_bot("Checkbox de términos marcado.")

        # Paso 8: Clic en "Accept and sign"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Accept and sign']")
        )).click()
        log_bot("Clic en 'Accept and sign'.")

        # --- FASE DE FIRMA ---
        log_bot("Iniciando fase de firma...")

        # Paso 9: Copiar mensaje a firmar
        message_element = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//div[contains(text(), 'I agree to abide by the terms')]")
        ))
        texto_challenge = message_element.text
        log_bot(f"Mensaje a firmar obtenido: '{texto_challenge[:50]}...'")

        # Paso 10: Firmar el mensaje (¡CON CIP-8 y CLAVE DE PAGO!)
        firma_hex = firmar_mensaje_cip8(signing_key, texto_challenge)
        log_bot("Mensaje firmado localmente (con CIP-8).")

        # --- ¡Guardar Firma en JSON! ---
        try:
            log_bot("Guardando firma en el archivo JSON...")
            wallet_data["generated_signature"] = firma_hex 
            with open(wallet_file_path, 'w') as f: 
                json.dump(wallet_data, f, indent=4)
            log_bot("Firma guardada en JSON con éxito.")
        except Exception as e:
            log_bot(f"ADVERTENCIA: No se pudo guardar la firma en el JSON: {e}", logging.WARNING)

        
        # --- ¡LÓGICA DE PEGADO Y EDICIÓN MANUAL! ---

        # Paso 11: Pegar la firma (con JS y Edición Manual)
        signature_textarea = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//textarea[@placeholder='Please enter the signature generated by your wallet']")
        ))
        
        log_bot("Pegando firma (JS + Edición Manual: Espacio y Borrado)...")
        # 1. Inyectar valor completo con JS
        driver.execute_script("arguments[0].value = arguments[1];", signature_textarea, firma_hex)
        # 2. Simular clic (foco)
        signature_textarea.click() 
        # 3. Añadir espacio
        signature_textarea.send_keys(Keys.SPACE)
        # 4. Borrar espacio
        signature_textarea.send_keys(Keys.BACKSPACE)
        log_bot("Firma pegada y edición simulada.")


        # Paso 12: Pegar la clave pública (con JS y Edición Manual)
        public_key_input = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@placeholder='Please enter a public key']")
        ))
        
        log_bot("Pegando clave pública (JS + Edición Manual: Espacio y Borrado)...")
        # 1. Inyectar valor completo con JS
        driver.execute_script("arguments[0].value = arguments[1];", public_key_input, public_key)
        # 2. Simular clic (foco)
        public_key_input.click()
        # 3. Añadir espacio
        public_key_input.send_keys(Keys.SPACE)
        # 4. Borrar espacio
        public_key_input.send_keys(Keys.BACKSPACE)
        log_bot("Clave pública pegada y edición simulada.")

        # --- FIN DE LÓGICA DE PEGADO Y EDICIÓN MANUAL ---


        # Paso 13: Clic en "Sign"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Sign']")
        )).click()
        log_bot("Clic en 'Sign'.")

        # --- FASE DE MINADO ---
        log_bot("Iniciando sesión de minado...")

        # Paso 14: Clic en "Start session"
        wait_long = WebDriverWait(driver, 40) 
        wait_long.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Start session']")
        )).click()
        log_bot("¡Sesión iniciada! Entrando en modo monitoreo.")

        # Paso 15: Bucle de monitoreo
        while True:
            try:
                # --- Sección Snapshot ---
                claim = wait.until(EC.visibility_of_element_located(
                    (By.XPATH, "//*[contains(text(), 'Your estimated claim:')]/following-sibling::span")
                )).text
                share = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Your estimated share:')]/following-sibling::span"
                ).text
                my_solutions = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Your submitted solutions:')]/following-sibling::span"
                ).text
                all_solutions = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'All submitted solutions:')]/following-sibling::span"
                ).text

                # --- Sección Miner Status ---
                miner_status = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Miner status')]/following-sibling::span"
                ).text
                current_challenge = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Current challenge:')]/following-sibling::span"
                ).text
                status = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Status:')]/following-sibling::span"
                ).text
                time_spent = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Time spent on this challenge:')]/following-sibling::span"
                ).text

                # --- Sección Day ---
                day = driver.find_element(
                    By.XPATH, "//div[contains(text(), 'Day:')]"
                ).text
                next_challenge = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Next challenge in:')]/following-sibling::span"
                ).text

                log_bot(f"PROGRESO: [{miner_status}] Claim: {claim} | Mis Sol: {my_solutions} | "
                    f"Challenge: {current_challenge} | Status: {status} | Próximo en: {next_challenge}")

            except (NoSuchElementException, TimeoutException) as e:
                log_bot(f"Error al leer datos de progreso (puede ser temporal): {str(e)[:100]}... Refrescando...", logging.WARNING)
                driver.refresh() # Refrescar la página si algo falla
            except Exception as e:
                log_bot(f"Error inesperado en el bucle de monitoreo: {e}", logging.ERROR)
                traceback.print_exc()
                
            time.sleep(60)

    except TimeoutException:
        log_bot("ERROR: Un elemento no se encontró o no estuvo clicable a tiempo. El bot se detendrá.", logging.ERROR)
        log_bot(f"URL actual: {driver.current_url}", logging.ERROR)
        traceback.print_exc()
    except Exception as e:
        log_bot(f"ERROR fatal en el bot: {e}", logging.ERROR)
        traceback.print_exc()
    finally:
        driver.quit()
        log_bot("Navegador cerrado. Proceso terminado.")


# =============================================================================
# SECCIÓN 3: LANZADOR PRINCIPAL (Corregido para lanzar N procesos secuencialmente)
# =============================================================================

# --- CONFIGURACIÓN DE LANZAMIENTO ---
DELAY_BETWEEN_LAUNCHES_SECONDS = 30 # <--- Retardo entre el inicio de cada bot/proceso
# ------------------------------------


if __name__ == "__main__":
    try:
        set_start_method('spawn')
    except RuntimeError:
        pass 

    # 1. Preguntar y gestionar carteras
    cantidad_a_lanzar = 0
    while True:
        try:
            # Preguntamos cuántos procesos (bots) quieres lanzar
            cantidad_a_lanzar = int(input("¿Cuántos procesos (bots) quieres lanzar en TOTAL? "))
            if cantidad_a_lanzar > 0:
                # La función gestiona_pool_de_carteras asegurará que existen al menos N carteras.
                gestionar_pool_de_carteras(cantidad_a_lanzar)
                break
            else:
                log.warning("Por favor, introduce un número positivo.")
        except ValueError:
            log.warning("Entrada no válida. Introduce un número.")

    # 2. Encontrar y seleccionar el número EXACTO de carteras a usar
    try:
        archivos_disponibles = [os.path.join(CARTERAS_DIR, f) 
                                for f in os.listdir(CARTERAS_DIR) 
                                if f.startswith('wallet_') and f.endswith('.json')]
        
        # Ordenamos los archivos por el número (ej: wallet_1 antes de wallet_10)
        archivos_disponibles.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0])) 
        
        # Seleccionamos EXACTAMENTE la cantidad de archivos a lanzar
        archivos_a_lanzar = archivos_disponibles[:cantidad_a_lanzar]
        
        if len(archivos_a_lanzar) < cantidad_a_lanzar:
            # Esto no debería pasar si la gestión de carteras fue exitosa.
            log.error(f"Error fatal: No se encontraron {cantidad_a_lanzar} carteras. Saliendo.")
            sys.exit()
            
    except FileNotFoundError:
        log.error(f"Directorio de carteras '{CARTERAS_DIR}' no encontrado. Saliendo.")
        sys.exit()
    except Exception as e:
        log.error(f"Error al seleccionar carteras: {e}. Asegúrate de que los nombres de archivo sean correctos (wallet_N.json).")
        traceback.print_exc()
        sys.exit()


    log.info(f"\nSe lanzarán {len(archivos_a_lanzar)} bots, uno por cada cartera seleccionada, con un retardo de {DELAY_BETWEEN_LAUNCHES_SECONDS}s entre cada uno.\n")
    time.sleep(3)

    # 3. Lanzar N procesos secuencialmente (CON RETARDO)
    procesos = []
    for i, wallet_file in enumerate(archivos_a_lanzar):
        p = Process(target=run_bot_worker, args=(wallet_file,))
        procesos.append(p)
        p.start()
        
        # Lógica de retardo para un inicio controlado
        wallet_id = os.path.basename(wallet_file).split('.')[0]
        log.info(f"Lanzando {wallet_id} de {len(archivos_a_lanzar)}... (Pausa de {DELAY_BETWEEN_LAUNCHES_SECONDS}s antes del siguiente)")
        
        # Esperamos el retardo configurado (excepto si es el último)
        if i < len(archivos_a_lanzar) - 1:
            time.sleep(DELAY_BETWEEN_LAUNCHES_SECONDS) 

    log.info(f"--- ¡{len(procesos)} bots están ahora ejecutándose en segundo plano! ---")
    log.info("Puedes ver su progreso en esta terminal.")
    log.info("Cierra esta ventana (o presiona Ctrl+C) para detener todos los bots.")

    # 4. Esperar a que todos los procesos terminen
    try:
        for p in procesos:
            p.join()
    except KeyboardInterrupt:
        log.info("\nDeteniendo todos los procesos...")
        for p in procesos:
            if p.is_alive():
                p.terminate()
                p.join()
        log.info("Todos los bots han sido detenidos.")