import { type NextRequest, NextResponse } from 'next/server';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { session } = body;

    if (!session) {
      return NextResponse.json({ error: 'Missing session token' }, { status: 400 });
    }

    const response = NextResponse.json({ success: true });
    
    response.headers.set(
      'Set-Cookie',
      `neon-session=${session}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000; Secure`
    );

    return response;
  } catch (e) {
    console.error('Session setup error:', e);
    return NextResponse.json({ error: 'Failed to set session' }, { status: 500 });
  }
}
