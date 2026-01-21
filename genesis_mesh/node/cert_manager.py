"""Certificate lifecycle management."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable
import time

from ..models.certificates import JoinCertificate


logger = logging.getLogger(__name__)


class CertificateManager:
    """
    Manages certificate lifecycle including auto-renewal.

    Responsibilities:
    - Monitor certificate expiration
    - Trigger renewal when 50% of validity remains
    - Handle renewal failures with exponential backoff
    - Graceful shutdown if renewal fails repeatedly
    """

    def __init__(
        self,
        node_id: str,
        get_certificate: Callable[[], Optional[JoinCertificate]],
        renew_certificate: Callable[[], JoinCertificate],
        on_certificate_renewed: Optional[Callable] = None,
        on_renewal_failed: Optional[Callable] = None
    ):
        """
        Initialize certificate manager.

        Args:
            node_id: Local node ID
            get_certificate: Function to get current certificate
            renew_certificate: Function to renew certificate
            on_certificate_renewed: Callback when cert is renewed
            on_renewal_failed: Callback when renewal fails
        """
        self.node_id = node_id
        self.get_certificate = get_certificate
        self.renew_certificate = renew_certificate
        self.on_certificate_renewed = on_certificate_renewed
        self.on_renewal_failed = on_renewal_failed

        self._renewal_task: Optional[asyncio.Task] = None
        self._running = False

        # Renewal tracking
        self._renewal_threshold = 0.5  # Renew at 50% of validity
        self._max_failures = 5
        self._failure_count = 0
        self._backoff_delays = [30, 60, 120, 300, 600]  # Exponential backoff (seconds)

    async def start(self):
        """Start certificate monitoring."""
        if self._running:
            return

        self._running = True
        self._renewal_task = asyncio.create_task(self._monitor_loop())
        logger.info("Certificate manager started")

    async def stop(self):
        """Stop certificate monitoring."""
        self._running = False
        if self._renewal_task:
            self._renewal_task.cancel()
            try:
                await self._renewal_task
            except asyncio.CancelledError:
                pass
        logger.info("Certificate manager stopped")

    async def _monitor_loop(self):
        """Monitor certificate expiration and trigger renewal."""
        try:
            while self._running:
                try:
                    # Check if renewal needed
                    cert = self.get_certificate()
                    if cert and self._should_renew(cert):
                        logger.info("Certificate renewal threshold reached")
                        await self._attempt_renewal()

                    # Check every minute
                    await asyncio.sleep(60)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in certificate monitor loop: {e}")
                    await asyncio.sleep(60)

        except asyncio.CancelledError:
            pass

    def _should_renew(self, cert: JoinCertificate) -> bool:
        """
        Check if certificate should be renewed.

        Args:
            cert: Certificate to check

        Returns:
            True if renewal needed
        """
        if cert.is_expired():
            logger.error("Certificate has already expired!")
            return True

        # Calculate remaining validity percentage
        now = datetime.utcnow()
        total_validity = (cert.valid_to - cert.valid_from).total_seconds()
        remaining = (cert.valid_to - now).total_seconds()
        percent_remaining = remaining / total_validity

        if percent_remaining <= self._renewal_threshold:
            logger.info(
                f"Certificate renewal needed: "
                f"{percent_remaining*100:.1f}% validity remaining"
            )
            return True

        return False

    async def _attempt_renewal(self):
        """Attempt to renew the certificate with exponential backoff."""
        while self._failure_count < self._max_failures:
            try:
                logger.info(f"Attempting certificate renewal (attempt {self._failure_count + 1})")

                # Renew certificate
                new_cert = await asyncio.to_thread(self.renew_certificate)

                # Verify new certificate
                if not new_cert or new_cert.is_expired():
                    raise ValueError("Received invalid certificate")

                # Reset failure count
                self._failure_count = 0

                logger.info(
                    f"Certificate renewed successfully "
                    f"(valid until {new_cert.valid_to})"
                )

                # Notify callback
                if self.on_certificate_renewed:
                    try:
                        await self.on_certificate_renewed(new_cert)
                    except Exception as e:
                        logger.error(f"Error in renewal callback: {e}")

                return

            except Exception as e:
                self._failure_count += 1
                logger.error(
                    f"Certificate renewal failed (attempt {self._failure_count}): {e}"
                )

                if self._failure_count >= self._max_failures:
                    logger.critical("Maximum renewal failures reached, shutting down")
                    if self.on_renewal_failed:
                        try:
                            await self.on_renewal_failed()
                        except Exception as callback_error:
                            logger.error(f"Error in renewal failed callback: {callback_error}")
                    return

                # Exponential backoff
                delay = self._backoff_delays[min(self._failure_count - 1, len(self._backoff_delays) - 1)]
                logger.info(f"Retrying in {delay} seconds...")
                await asyncio.sleep(delay)

    def get_time_until_renewal(self) -> Optional[float]:
        """
        Get seconds until renewal is needed.

        Returns:
            Seconds until renewal, or None if no certificate
        """
        cert = self.get_certificate()
        if not cert:
            return None

        now = datetime.utcnow()
        total_validity = (cert.valid_to - cert.valid_from).total_seconds()
        remaining = (cert.valid_to - now).total_seconds()
        renewal_time = total_validity * self._renewal_threshold

        time_until_renewal = remaining - renewal_time

        return max(0, time_until_renewal)

    def get_certificate_status(self) -> dict:
        """Get certificate status information."""
        cert = self.get_certificate()
        if not cert:
            return {
                "has_certificate": False,
                "error": "No certificate"
            }

        now = datetime.utcnow()
        total_validity = (cert.valid_to - cert.valid_from).total_seconds()
        remaining = (cert.valid_to - now).total_seconds()
        percent_remaining = (remaining / total_validity) * 100

        return {
            "has_certificate": True,
            "certificate_id": cert.certificate_id,
            "valid_from": cert.valid_from.isoformat(),
            "valid_to": cert.valid_to.isoformat(),
            "is_expired": cert.is_expired(),
            "percent_remaining": round(percent_remaining, 2),
            "seconds_remaining": round(remaining, 0),
            "should_renew": self._should_renew(cert),
            "renewal_failures": self._failure_count,
        }

    async def force_renewal(self):
        """Force immediate certificate renewal."""
        logger.info("Forcing immediate certificate renewal")
        await self._attempt_renewal()
