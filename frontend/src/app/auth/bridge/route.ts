import { type NextRequest, NextResponse } from 'next/server';
import { createHash, randomBytes } from 'crypto';

const BRIDGE_SECRET = process.env.BRIDGE_SECRET || 'dev-bridge-secret-change-in-prod';

interface BridgeToken {
  session: string;
  exp: number;
  nonce: string;
}

function sign(data: string): string {
  return createHash('sha256')
    .update(data + BRIDGE_SECRET)
    .digest('hex')
    .slice(0, 32);
}

function encodeBridgeToken(session: string): string {
  const exp = Date.now() + 60000; // 1 minute expiry
  const nonce = randomBytes(8).toString('hex');
  const payload = Buffer.from(JSON.stringify({ session, exp, nonce })).toString('base64url');
  const signature = sign(payload);
  return `${payload}.${signature}`;
}

function decodeBridgeToken(token: string): string | null {
  const parts = token.split('.');
  if (parts.length !== 2) return null;
  
  const [payload, signature] = parts;
  const expectedSig = sign(payload);
  
  if (signature !== expectedSig) return null;
  
  try {
    const data: BridgeToken = JSON.parse(Buffer.from(payload, 'base64url').toString());
    if (data.exp < Date.now()) return null;
    return data.session;
  } catch {
    return null;
  }
}

export { encodeBridgeToken, decodeBridgeToken };

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const returnTo = searchParams.get('return_to');
  
  if (!returnTo) {
    return NextResponse.redirect(new URL('/', request.url));
  }

  try {
    const returnURL = new URL(returnTo);
    
    // Only allow same Vercel project previews
    const allowedHosts = [
      'frontend-red-one-13.vercel.app',
      'localhost:3000'
    ];
    const isAllowed = allowedHosts.some(h => returnURL.hostname === h) ||
                      (returnURL.hostname.endsWith('.vercel.app') && 
                       returnURL.hostname.includes('--frontend-red-one-13'));
    
    if (!isAllowed) {
      return NextResponse.redirect(new URL('/?error=invalid_redirect', request.url));
    }

    const sessionCookie = request.cookies.get('neon-session')?.value;
    
    if (!sessionCookie) {
      return NextResponse.redirect(new URL('/?error=no_session', request.url));
    }

    // Generate signed one-time token
    const bridgeToken = encodeBridgeToken(sessionCookie);
    
    const bridgeURL = new URL('/auth/callback', returnURL);
    bridgeURL.searchParams.set('token', bridgeToken);
    return NextResponse.redirect(bridgeURL);
  } catch (e) {
    console.error('Auth bridge error:', e);
    return NextResponse.redirect(new URL('/?error=bridge_failed', request.url));
  }
}
