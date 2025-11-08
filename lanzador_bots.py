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
# SECCIÓN 1: GESTOR DE CARTERAS (Sin cambios)
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
# SECCIÓN 2: LÓGICA DEL BOT (WORKER) - (Sin cambios)
# =============================================================================

# Código de Salida Especial para "Cambio de Challenge"
EXIT_CODE_EPOCH_CHANGE = 100

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
    Ha sido actualizada para detectar:
    1.  SOLVED: Sale con 'exit 0' (Éxito) para rotar a una NUEVA wallet.
    2.  EPOCH CHANGE: Sale con 'exit 100' (Cambio) para rotar a la wallet PRINCIPAL.
    3.  CRASH: Sale con 'exit 1' (Error) para reiniciar la MISMA wallet.
    4.  Ctrl+C: Es capturado por el 'finally' para cerrar el driver limpiamente.
    """
    
    # Extraer un ID simple para los logs, ej: "wallet_1"
    wallet_id = os.path.basename(wallet_file_path).split('.')[0]
    
    def log_bot(mensaje, level=logging.INFO):
        # Función helper para que todos los logs de este bot tengan su ID
        log.log(level, f"[{wallet_id}] {mensaje}")

    log_bot(f"Bot iniciado. Cargando datos de cartera: {wallet_file_path}")

    # 1. Cargar datos de la cartera
    wallet_data = {} 
    try:
        with open(wallet_file_path, 'r') as f:
            wallet_data = json.load(f)
        
        address = wallet_data["address"]
        public_key = wallet_data["public_key_hex"]
        private_key_hex = wallet_data["payment_private_key_hex"] 
        private_key_bytes = bytes.fromhex(private_key_hex)
        signing_key = PaymentSigningKey(private_key_bytes) 
        
        log_bot(f"Cartera cargada. Dirección: {address[:20]}...")
        
    except Exception as e:
        log_bot(f"ERROR: No se pudo cargar o parsear el archivo {wallet_file_path}: {e}", logging.ERROR)
        traceback.print_exc()
        return # Sale con error (no 0), el manager lo reiniciará

    # 2. Configurar Selenium
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/5.37.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36")
    
    driver = None # Definir el driver fuera del try para el 'finally'
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        wait = WebDriverWait(driver, 20) 
        log_bot("Navegador iniciado.")
    except Exception as e:
        log_bot(f"ERROR: No se pudo iniciar Selenium. {e}", logging.ERROR)
        traceback.print_exc()
        if driver:
            driver.quit() # Asegurarse de cerrar si el 'wait' falla
        return # Sale con error (no 0), el manager lo reiniciará

    # 3. Bucle principal del bot (Lógica de clics)
    try:
        # Paso 1: Ir a la página
        driver.get("https://sm.midnight.gd/wizard/mine")
        log_bot(f"Abierta la página: {driver.title}")

        # --- INICIO LÓGICA DE LOGIN ---
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
        message_element = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//div[contains(text(), 'I agree to abide by the terms')]")
        ))
        texto_challenge = message_element.text
        firma_hex = firmar_mensaje_cip8(signing_key, texto_challenge)
        
        # --- ¡Guardar Firma en JSON! ---
        try:
            wallet_data["generated_signature"] = firma_hex 
            with open(wallet_file_path, 'w') as f: 
                json.dump(wallet_data, f, indent=4)
        except Exception as e:
            log_bot(f"ADVERTENCIA: No se pudo guardar la firma en el JSON: {e}", logging.WARNING)

        # --- ¡LÓGICA DE PEGADO Y EDICIÓN MANUAL! ---
        signature_textarea = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//textarea[@placeholder='Please enter the signature generated by your wallet']")
        ))
        driver.execute_script("arguments[0].value = arguments[1];", signature_textarea, firma_hex)
        signature_textarea.click() 
        signature_textarea.send_keys(Keys.SPACE)
        signature_textarea.send_keys(Keys.BACKSPACE)
        
        public_key_input = wait.until(EC.visibility_of_element_located(
            (By.XPATH, "//input[@placeholder='Please enter a public key']")
        ))
        driver.execute_script("arguments[0].value = arguments[1];", public_key_input, public_key)
        public_key_input.click()
        public_key_input.send_keys(Keys.SPACE)
        public_key_input.send_keys(Keys.BACKSPACE)

        # Paso 13: Clic en "Sign"
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Sign']")
        )).click()
        log_bot("Clic en 'Sign'.")
        # --- FIN LÓGICA LOGIN ---


        # Paso 14: Clic en "Start session"
        wait_long = WebDriverWait(driver, 40) 
        wait_long.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[text()='Start session']")
        )).click()
        log_bot("¡Sesión iniciada! Estabilizando para capturar estado inicial...")

        # --- ¡NUEVO! Capturar estado inicial ---
        time.sleep(10) # Espera 10s para que la página se estabilice
        initial_solved_challenges = -1
        initial_challenge_id = "-1"
        try:
            initial_solved_challenges_str = wait.until(EC.visibility_of_element_located(
                (By.XPATH, "//span[@data-testid='solved-count']")
            )).text
            initial_solved_challenges = int(initial_solved_challenges_str)
            
            initial_challenge_id = driver.find_element(
                By.XPATH, "//*[contains(text(), 'Current challenge:')]/following-sibling::span"
            ).text
            
            log_bot(f"Estado inicial capturado -> Solved: {initial_solved_challenges}, Challenge ID: {initial_challenge_id}")
        except Exception as e:
            log_bot(f"Error capturando estado inicial. Asumiendo 0. Error: {e}", logging.WARNING)
            initial_solved_challenges = 0 # Fallback
            initial_challenge_id = "0" # Fallback
        # --- FIN NUEVO ---


        # Paso 15: Bucle de monitoreo (¡CÓDIGO DE ROTACIÓN ACTUALIZADO!)
        while True:
            try:
                # --- Sección Snapshot ---
                claim = wait.until(EC.visibility_of_element_located(
                    (By.XPATH, "//*[contains(text(), 'Your estimated claim:')]/following-sibling::span")
                )).text
                my_solutions = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Your submitted solutions:')]/following-sibling::span"
                ).text
                all_solutions_submitted = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'All submitted solutions:')]/following-sibling::span"
                ).text

                # --- Capturar estado actual ---
                all_challenges = driver.find_element(
                    By.XPATH, "//span[@data-testid='all-count']"
                ).text
                current_solved_challenges_str = driver.find_element(
                    By.XPATH, "//span[@data-testid='solved-count']"
                ).text
                current_solved_challenges = int(current_solved_challenges_str)
                unsolved_challenges = driver.find_element(
                    By.XPATH, "//span[@data-testid='unsolved-count']"
                ).text
                next_challenge_in = driver.find_element(
                    By.XPATH, "//div[contains(span, 'Next challenge in:')]/span[2]"
                ).text
                
                # --- Sección Miner Status ---
                miner_status = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Miner status')]/following-sibling::span//span[1]"
                ).text
                current_challenge_id = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Current challenge:')]/following-sibling::span"
                ).text
                status = driver.find_element(
                    By.XPATH, "//*[contains(text(), 'Status:')]/following-sibling::span/span[1]"
                ).text

                # --- Log de Progreso ---
                log_bot("----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------")
                log_bot(f"PROGRESO: [{miner_status}] Claim: {claim} | Mis Sol: {my_solutions} / {all_solutions_submitted}")
                log_bot(f"CHALLENGE STATUS: All: {all_challenges} | Solved: {current_solved_challenges} (Initial: {initial_solved_challenges}) | Unsolved: {unsolved_challenges} | Current ID: {current_challenge_id} (Initial: {initial_challenge_id})")
                log_bot(f"MINER STATUS: {status} | Próximo en: {next_challenge_in}")
                log_bot("----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------")

                # --- ¡NUEVO! Lógica de salida por éxito ---
                if current_solved_challenges > initial_solved_challenges:
                    log_bot(f"¡ÉXITO! Challenge resuelto. (Solved: {current_solved_challenges} > {initial_solved_challenges})")
                    log_bot("Cerrando este worker para rotación de NUEVA wallet. Saliendo con código 0...")
                    driver.quit()
                    sys.exit(0) # Salir con código 0 (Éxito)

                # --- ¡NUEVO! Lógica de salida por Cambio de Challenge ---
                if current_challenge_id != initial_challenge_id:
                    log_bot(f"¡CAMBIO DE CHALLENGE! Nuevo ID: {current_challenge_id} (vs {initial_challenge_id}).")
                    log_bot("Cerrando este worker para rotación a wallet PRINCIPAL. Saliendo con código 100...")
                    driver.quit()
                    sys.exit(EXIT_CODE_EPOCH_CHANGE) # Salir con código 100 (Cambio de Epoch)

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
        # 'finally' se ejecutará, saliendo con código de error
    except Exception as e:
        log_bot(f"ERROR fatal en el bot: {e}", logging.ERROR)
        traceback.print_exc()
        # 'finally' se ejecutará, saliendo con código de error
    finally:
        # ¡IMPORTANTE! Este 'finally' asegura que Chrome se cierre
        # si ocurre cualquier error no manejado (Timeout, etc.)
        # O si el proceso recibe un KeyboardInterrupt (Ctrl+C).
        if driver:
            driver.quit()
        log_bot("Navegador cerrado. Proceso terminado (por 'finally').")


# =============================================================================
# SECCIÓN 3: SUPERVISOR DE WORKERS (ACTUALIZADO CON CIERRE LIMPIO)
# =============================================================================

# --- CONFIGURACIÓN DE LANZAMIENTO ---
DELAY_BETWEEN_LAUNCHES_SECONDS = 30 # Retardo para el lanzamiento INICIAL de cada bot
MANAGER_SLEEP_SECONDS = 10         # Tiempo que el supervisor espera antes de comprobar el estado de los workers
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
            cantidad_a_lanzar = int(input("¿Cuántos procesos (bots) quieres lanzar en TOTAL? "))
            if cantidad_a_lanzar > 0:
                log.info(f"Asegurando que existan al menos {cantidad_a_lanzar} carteras...")
                gestionar_pool_de_carteras(cantidad_a_lanzar)
                break
            else:
                log.warning("Por favor, introduce un número positivo.")
        except ValueError:
            log.warning("Entrada no válida. Introduce un número.")

    # 2. Preparar la lista inicial y la cola de carteras
    try:
        archivos_disponibles = [os.path.join(CARTERAS_DIR, f) 
                                for f in os.listdir(CARTERAS_DIR) 
                                if f.startswith('wallet_') and f.endswith('.json')]
        
        archivos_disponibles.sort(key=lambda x: int(os.path.basename(x).split('_')[1].split('.')[0])) 
        
        # Estas son las N carteras "principales"
        principal_wallets = archivos_disponibles[:cantidad_a_lanzar]
        
        # Esta es la cola de carteras de reemplazo
        wallet_queue = [f for f in archivos_disponibles if f not in principal_wallets]
        log.info(f"{len(wallet_queue)} carteras en cola de reemplazo.")

        # Este es el ID de la próxima cartera a generar si la cola se vacía
        next_wallet_id_to_gen = len(archivos_disponibles) + 1
        
        if len(principal_wallets) < cantidad_a_lanzar:
            log.error(f"Error fatal: No se pudieron preparar {cantidad_a_lanzar} carteras. Saliendo.")
            sys.exit()
            
    except Exception as e:
        log.error(f"Error al preparar las carteras: {e}.")
        traceback.print_exc()
        sys.exit()


    log.info(f"\nSe lanzarán {cantidad_a_lanzar} workers (slots), con un retardo de {DELAY_BETWEEN_LAUNCHES_SECONDS}s entre cada uno.\n")
    time.sleep(3)

    # 3. Lanzar N procesos iniciales
    worker_slots = [] # Esta lista mantendrá el estado de nuestros slots
    for i in range(cantidad_a_lanzar):
        wallet_file = principal_wallets[i]
        wallet_id_log = os.path.basename(wallet_file).split('.')[0]
        
        log.info(f"Iniciando Slot {i} con {wallet_id_log} (Principal)...")
        p = Process(target=run_bot_worker, args=(wallet_file,))
        p.start()
        
        worker_slots.append({
            "id": i,
            "process": p,
            "current_wallet_file": wallet_file,   # La wallet que está corriendo AHORA
            "principal_wallet_file": wallet_file  # La wallet principal de ESTE slot
        })
        
        log.info(f"Slot {i} ({wallet_id_log}) lanzado. (Pausa de {DELAY_BETWEEN_LAUNCHES_SECONDS}s)")
        time.sleep(DELAY_BETWEEN_LAUNCHES_SECONDS) 

    log.info(f"--- ¡{len(worker_slots)} workers están ahora ejecutándose! ---")
    log.info(f"Iniciando bucle del Supervisor (comprobando cada {MANAGER_SLEEP_SECONDS}s).")
    log.info("Cierra esta ventana (o presiona Ctrl+C) para detener todos los bots.")

    # 4. Bucle del Supervisor (Manager Loop)
    try:
        while True:
            # Comprobar el estado de cada slot
            for slot in worker_slots:
                
                # Si el proceso del slot está muerto, actuar
                if not slot["process"].is_alive():
                    exit_code = slot["process"].exitcode
                    old_wallet = os.path.basename(slot["current_wallet_file"]).split('.')[0]
                    principal_wallet_file = slot["principal_wallet_file"]
                    principal_wallet_name = os.path.basename(principal_wallet_file).split('.')[0]
                    slot_id = slot["id"]

                    # CASO 1: ÉXITO (Challenge Resuelto, Exit Code 0)
                    if exit_code == 0:
                        log.info(f"Slot {slot_id} ({old_wallet}) completó challenge. ROTANDO a NUEVA wallet...")
                        
                        # 1. Obtener nueva cartera de la cola
                        if wallet_queue:
                            new_wallet_file = wallet_queue.pop(0)
                            log.info(f"Siguiente cartera de la cola: {os.path.basename(new_wallet_file)}")
                        else:
                            # 2. Si no hay, generar una nueva
                            log.info(f"Cola de carteras vacía. Generando nueva cartera: wallet_{next_wallet_id_to_gen}...")
                            gestionar_pool_de_carteras(next_wallet_id_to_gen)
                            new_wallet_file = os.path.join(CARTERAS_DIR, f"wallet_{next_wallet_id_to_gen}.json")
                            next_wallet_id_to_gen += 1
                        
                        # 3. Lanzar nuevo proceso en el slot
                        log.info(f"Iniciando Slot {slot_id} con {os.path.basename(new_wallet_file)}...")
                        p = Process(target=run_bot_worker, args=(new_wallet_file,))
                        p.start()
                        slot["process"] = p
                        slot["current_wallet_file"] = new_wallet_file # Actualiza la wallet actual

                    # CASO 2: CAMBIO DE CHALLENGE (Exit Code 100)
                    elif exit_code == EXIT_CODE_EPOCH_CHANGE:
                        log.info(f"Slot {slot_id} ({old_wallet}) detectó CAMBIO DE CHALLENGE.")
                        log.info(f"Rotando de vuelta a la wallet PRINCIPAL: {principal_wallet_name}")
                        
                        # 1. Lanzar nuevo proceso con la wallet PRINCIPAL
                        p = Process(target=run_bot_worker, args=(principal_wallet_file,))
                        p.start()
                        slot["process"] = p
                        slot["current_wallet_file"] = principal_wallet_file # Vuelve a la principal

                    # CASO 3: CRASH (Cualquier otro Exit Code != 0)
                    else:
                        log.warning(f"Slot {slot_id} ({old_wallet}) crasheó (Exitcode: {exit_code}). REINICIANDO con la misma cartera...")
                        
                        # 1. Lanzar nuevo proceso con la MISMA cartera que crasheó
                        p = Process(target=run_bot_worker, args=(slot["current_wallet_file"],))
                        p.start()
                        slot["process"] = p
                        log.info(f"Slot {slot_id} ({old_wallet}) reiniciado.")

            # Esperar antes de la próxima comprobación
            time.sleep(MANAGER_SLEEP_SECONDS)

    except KeyboardInterrupt:
        # --- ¡BLOQUE ACTUALIZADO PARA CIERRE LIMPIO! ---
        log.info("\n[SUPERVISOR] Cierre por Ctrl+C detectado. Dando tiempo a los workers para cerrar limpiamente...")
        # No enviamos terminate(). Los workers (hijos) también reciben el Ctrl+C
        # y ejecutarán sus propios bloques 'finally' para llamar a driver.quit().
        # Aquí, el supervisor solo debe ESPERAR a que terminen (join).
        for slot in worker_slots:
            if slot["process"].is_alive():
                log.info(f"[SUPERVISOR] Esperando al Slot {slot['id']} (PID: {slot['process'].pid})...")
                slot["process"].join() # Espera a que el proceso hijo termine limpiamente
        log.info("[SUPERVISOR] Todos los workers han sido detenidos.")
        # --- FIN DE LA ACTUALIZACIÓN ---

    except Exception as e:
        log.error(f"Error fatal en el Supervisor: {e}")
        traceback.print_exc()
        # Intentar limpieza (modo "forzado" si el supervisor falla)
        for slot in worker_slots:
            if slot["process"].is_alive():
                log.warning(f"Forzando terminación del Slot {slot['id']}...")
                slot["process"].terminate()