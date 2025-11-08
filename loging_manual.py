import os
import json
import traceback
import logging
from pycardano import PaymentSigningKey
from pycardano.cip import cip8

# --- Configuración ---
CARTERAS_DIR = "pool_de_carteras"
# Configuración de Logging simple para esta herramienta
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger()
# ---------------------

def firmar_mensaje_cip8(payment_signing_key: PaymentSigningKey, message_str: str) -> str:
    """
    Firma un mensaje usando el estándar CIP-8 con la Payment Signing Key.
    (Función copiada de lanzador_bots.py)
    """
    try:
        # La función cip8.sign de pycardano toma la cadena de mensaje (message_str)
        # y devuelve la firma COSE en formato hexadecimal.
        signed_message_hex = cip8.sign(
            message=message_str,
            signing_key=payment_signing_key, 
            attach_cose_key=False 
        )
        return signed_message_hex
    except Exception as e:
        log.error(f"Error al firmar el mensaje CIP-8: {e}")
        return ""

def iniciar_sesion_manual():
    """
    Permite al usuario seleccionar una cartera, ver su dirección y firmar un mensaje.
    """
    log.info("--- Herramienta de Login Manual y Firma CIP-8 ---")
    
    # 1. Solicitar el ID de la cartera
    wallet_id = input("Introduce el ID de la cartera a cargar (ej: 1, 5, 20): ").strip()
    wallet_filename = f"wallet_{wallet_id}.json"
    wallet_file_path = os.path.join(CARTERAS_DIR, wallet_filename)
    
    if not os.path.exists(wallet_file_path):
        log.error(f"Error: No se encontró el archivo '{wallet_file_path}'. Asegúrate de que el ID es correcto.")
        return

    # 2. Cargar datos de la cartera
    try:
        with open(wallet_file_path, 'r') as f:
            wallet_data = json.load(f)
        
        address = wallet_data.get("address")
        public_key = wallet_data.get("public_key_hex")
        private_key_hex = wallet_data.get("payment_private_key_hex")
        
        if not address or not public_key or not private_key_hex:
            log.error("Error: El archivo JSON de la cartera está incompleto (faltan claves).")
            return
            
        private_key_bytes = bytes.fromhex(private_key_hex)
        signing_key = PaymentSigningKey(private_key_bytes) 
        
        log.info(f"\n✅ Cartera '{wallet_id}' cargada con éxito.")
        log.info("---------------------------------------------------------------------------------------------------")
        log.info(f"Dirección Completa: {address}")
        log.info("---------------------------------------------------------------------------------------------------")

    except Exception as e:
        log.error(f"Error al cargar o procesar el archivo de cartera: {e}")
        traceback.print_exc()
        return

    # 3. Solicitar mensaje para firmar
    print("\n")
    message_to_sign = input("Introduce el mensaje exacto que quieres firmar (ej: I agree to abide by the terms...): ")
    
    if not message_to_sign:
        log.warning("No se introdujo ningún mensaje. Proceso de firma cancelado.")
        return

    # 4. Generar la firma
    log.info("\nGenerando firma CIP-8...")
    firma_hex = firmar_mensaje_cip8(signing_key, message_to_sign)

    if firma_hex:
        log.info("\n--- RESULTADOS DE LA FIRMA CIP-8 ---")
        log.info(f"✅ Éxito al firmar el mensaje.")
        log.info(f"CLAVE PÚBLICA (Public Key): {public_key}")
        log.info(f"FIRMA COSE (Signature): {firma_hex}")
        log.info("------------------------------------")
        log.info("Estos valores son los que debes pegar en el formulario web.")
    else:
        log.error("Fallo al generar la firma. Revisa los logs de error.")


if __name__ == "__main__":
    iniciar_sesion_manual()