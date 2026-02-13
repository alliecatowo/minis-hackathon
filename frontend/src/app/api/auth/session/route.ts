import { type NextRequest, NextResponse } from 'next/server';
import { decodeBridgeToken } from '@/app/auth/bridge/route';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { token } = body;

    if (!token) {
      return NextResponse.json({ error: 'Missing token' }, { status: 400 });
    }

    // Decode and validate the bridge token
    const session = decodeBridgeToken(token);
    
    if (!session) {
      return NextResponse.json({ error: 'Invalid or expired token' }, { status: 401 });
    }

    const response = NextResponse.json({ success: true });
    
    // Set the session cookie with proper security attributes
    response.headers.set(
      'Set-Cookie',
      `neon-session=${session}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000; Secure`
    );

    return response;
  } catch (e) {
    console.error('Session setup error:', e);
    return NextResponse.json({ error: 'Failed to set session' }, { status: 500 });
  }
}
