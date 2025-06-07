import os
import datetime
import logging # For type hinting or direct use if needed
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

def generate_self_signed_cert(cert_path: str, key_path: str, hostname: str = "localhost", logger: logging.Logger = None):
    """
    Generates a new self-signed SSL certificate.
    """
    if logger:
        logger.info(f"Generating new self-signed SSL certificate for {hostname}...")
    else:
        print(f"Generating new self-signed SSL certificate for {hostname}...") # Fallback if no logger

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"CA"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"AkServerCity"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"AkServer SelfSigned"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    certificate = builder.sign(key, hashes.SHA256())
    certificate_pem = certificate.public_bytes(serialization.Encoding.PEM)
    with open(cert_path, "wb") as f:
        f.write(certificate_pem)
    with open(key_path, "wb") as f:
        f.write(private_key_pem)
    
    if logger:
        logger.info(f"Certificate saved to {cert_path}, key saved to {key_path}")
    else:
        print(f"Certificate saved to {cert_path}, key saved to {key_path}")