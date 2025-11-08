import sys
import traceback
import logging
from pycardano import PaymentSigningKey, HDWallet, PaymentVerificationKey
from pycardano.cip import cip8
from mnemonic.mnemonic import Mnemonic
from typing import Tuple

# --- Configuración ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger()
PAYMENT_DERIVATION_PATH = "m/1852'/1815'/0'/0/0"
# ---------------------

def derivar_claves_desde_semilla(seed_phrase: str) -> Tuple[PaymentSigningKey, str]:
    """
    Deriva la clave de firma de pago (Signing Key) y la clave pública (HEX) 
    a partir de la frase semilla.
    """
    try:
        # 1. Convierte la frase en semilla BIP39 (64 bytes) -> HEX (Lógica que funciona en tu entorno)
        mnemo_lib = Mnemonic("english")
        seed_bytes = mnemo_lib.to_seed(seed_phrase)
        seed_hex_string = seed_bytes.hex()
        root_key = HDWallet.from_seed(seed_hex_string)

        # 2. Deriva la clave de pago (m/1852'/1815'/0'/0/0)
        payment_derived_key = root_key.derive_from_path(PAYMENT_DERIVATION_PATH)
        
        # 3. Obtiene la clave privada (FIX: usando .xprivate_key y slicing para tu versión)
        payment_private_key_seed_32 = payment_derived_key.xprivate_key[0:32]
        payment_signing_key = PaymentSigningKey(payment_private_key_seed_32)

        # 4. Obtiene la clave de verificación/pública
        payment_verification_key = PaymentVerificationKey.from_signing_key(payment_signing_key)
        public_key_hex = payment_verification_key.payload.hex()
        
        return payment_signing_key, public_key_hex

    except Exception as e:
        log.error(f"Error en la derivación de claves: {e}")
        traceback.print_exc()
        raise

def firmar_mensaje_cip8(payment_signing_key: PaymentSigningKey, message_str: str) -> str:
    """Firma un mensaje usando el estándar CIP-8."""
    signed_message_hex = cip8.sign(
        message=message_str,
        signing_key=payment_signing_key,
        attach_cose_key=False
    )
    return signed_message_hex

def mostrar_uso_y_salir():
    """Muestra la sintaxis correcta del comando y sale."""
    print("\n--- Herramienta de Firma CIP-8 CLI (Por Frase Semilla) ---")
    print("Uso: py sign_by_seed.py \"<FRASE_SEMILLA_COMPLETA>\" \"<MENSAJE_A_FIRMAR>\"")
    print("\nEjemplo:")
    print("py sign_by_seed.py \"word1 word2 ... word24\" \"I agree to abide by the terms\"")
    print("\nNota: Usa comillas dobles (\") para encerrar la frase y el mensaje.")
    sys.exit(1)

def ejecutar_firma_por_seed():
    """
    Ejecuta el proceso de firma usando la frase semilla y el mensaje de línea de comandos.
    """
    
    # 1. Validar y obtener argumentos
    if len(sys.argv) < 3:
        mostrar_uso_y_salir()
    
    seed_phrase = sys.argv[1]
    message_to_sign = sys.argv[2]
    
    # 2. Derivar claves
    try:
        log.info("Derivando claves desde la frase semilla...")
        signing_key, public_key_hex = derivar_claves_desde_semilla(seed_phrase)
        
    except Exception:
        log.error("Fallo al derivar claves. Verifica que la frase semilla sea válida.")
        sys.exit(1)

    # 3. Generar la firma
    log.info(f"Firma iniciada para mensaje: \"{message_to_sign[:50]}...\"")
    
    firma_hex = firmar_mensaje_cip8(signing_key, message_to_sign)

    # 4. Devolver resultados
    if firma_hex:
        print("\n--- RESULTADOS DE LA FIRMA CIP-8 ---")
        print(f"CLAVE PÚBLICA (Verification Key): {public_key_hex}")
        print(f"FIRMA COSE (Signature): {firma_hex}")
        print("------------------------------------")
    else:
        log.error("Fallo al generar la firma. Revisa los logs.")
        sys.exit(1)


if __name__ == "__main__":
    ejecutar_firma_por_seed()